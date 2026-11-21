"""Propose new DSL specs from experiment memory — OpenAI or deterministic mutations."""

from __future__ import annotations

import copy
import json
import random
from typing import Any

from app.backtest.dsl import ENTRY_TYPES, validate_spec
from app.core.config import get_settings
from app.services.ai_research import DSL_HINT
from app.services.strategy_search_space import FAMILY_BUILDERS, refine_spec

MUTATE_BATCH_HINT_PREFIX = """
You are continuing a systematic futures search. Given trial results, propose NEW specifications.
Return JSON only:
{
  "rationale": "2-4 sentences",
  "specifications": [ {same shape as single specification in prior hint}, ... ]
}
Rules:
- instrument_symbol must match the requested symbol; timeframe 5m or 15m; session RTH Chicago; session_end_flatten true.
- Intraday prop desk: favor setups with realistic win rate (tighter targets vs stops, not 20% WR lottery tickets).
- Vary entry params and stop/target; use invert only when fading a documented anti-edge.
- Unique name per spec (include param summary).
- Maximum {max_specs} specifications.
"""


def _sanitize_spec(spec: dict, symbol: str) -> dict | None:
    copy_spec = copy.deepcopy(spec)
    copy_spec["instrument_symbol"] = symbol.upper()
    copy_spec.setdefault("session", {"allowed": ["RTH"], "timezone": "America/Chicago"})
    exit_spec = copy_spec.setdefault("exit", {})
    exit_spec.setdefault("session_end_flatten", True)
    errors = validate_spec(copy_spec)
    if errors:
        return None
    etype = (copy_spec.get("entry") or {}).get("type")
    if etype not in ENTRY_TYPES:
        return None
    return copy_spec


def _heuristic_mutations(symbol: str, memory_summary: str, n: int, *, seed: int | None) -> list[dict]:
    """Parse near-miss names from summary and apply refine + random family draws."""
    rng = random.Random(seed)
    specs: list[dict] = []
    pools = []
    for builder in FAMILY_BUILDERS.values():
        pool = list(builder(symbol))
        if pool:
            pools.append(pool)
    if not pools:
        return []
    for _ in range(n):
        base = copy.deepcopy(rng.choice(rng.choice(pools)))
        mutated = rng.choice(refine_spec(base)) if rng.random() < 0.6 else base
        entry = mutated.setdefault("entry", {})
        etype = entry.get("type")
        if etype == "opening_range_breakout":
            entry["range_minutes"] = rng.choice((10, 15, 20, 25, 30))
        elif etype == "vwap_reversion":
            entry["deviation_ticks"] = rng.choice((12, 16, 20, 24))
        elif etype == "ema_crossover":
            fast, slow = rng.choice(((8, 21), (9, 26), (12, 26)))
            entry["fast_period"], entry["slow_period"] = fast, slow
        elif etype == "rsi_reversion":
            entry["oversold"], entry["overbought"] = rng.choice(((28, 72), (32, 68), (35, 65)))
        stop = int(mutated["exit"].get("stop_ticks", 12))
        target = int(mutated["exit"].get("target_ticks", 20))
        if target > stop * 2:
            mutated["exit"]["target_ticks"] = stop * 2
        mutated["name"] = f"{mutated['name']} AI {len(specs) + 1}"
        clean = _sanitize_spec(mutated, symbol)
        if clean:
            specs.append(clean)
    return specs[:n]


def _parse_spec_list(content: str) -> list[dict]:
    parsed = json.loads(content)
    if isinstance(parsed, list):
        return parsed
    specs = parsed.get("specifications") or parsed.get("specs") or []
    if not isinstance(specs, list):
        return []
    return specs


def propose_search_specs(
    symbol: str,
    memory_summary: str,
    *,
    max_specs: int = 12,
    seed: int | None = None,
    provider_slug: str | None = None,
    model: str | None = None,
) -> tuple[str, list[dict]]:
    hint = MUTATE_BATCH_HINT_PREFIX.replace("{max_specs}", str(max_specs)) + DSL_HINT
    user = f"Symbol: {symbol}\n\nTrial memory:\n{memory_summary}\n\n{hint}"
    system = "CME index futures quant researcher. Output JSON only."

    from app.services.ai_arena.llm_providers import get_provider

    slug = provider_slug
    if not slug:
        settings = get_settings()
        slug = "openai" if settings.ai_configured else None

    provider = get_provider(slug) if slug else None
    if not provider or not provider.api_key_configured():
        specs = _heuristic_mutations(symbol, memory_summary, max_specs, seed=seed)
        return "Heuristic mutations (configure researcher LLM API key for directed search).", specs

    use_model = model or provider.default_model
    try:
        result = provider.complete_json(system=system, user=user, model=use_model)
        rationale = str(result.data.get("rationale", "AI mutation round"))
        raw_specs = result.data.get("specifications") or result.data.get("specs") or []
        if not isinstance(raw_specs, list):
            raw_specs = _parse_spec_list(json.dumps(result.data))
    except Exception:
        specs = _heuristic_mutations(symbol, memory_summary, max_specs, seed=seed)
        return f"{provider.slug} unavailable — heuristic mutations.", specs

    out: list[dict] = []
    seen: set[str] = set()
    for raw in raw_specs:
        if not isinstance(raw, dict):
            continue
        clean = _sanitize_spec(raw, symbol)
        if not clean:
            continue
        name = clean.get("name", "")
        if name in seen:
            clean["name"] = f"{name} alt{len(out)}"
        seen.add(clean["name"])
        out.append(clean)
        if len(out) >= max_specs:
            break
    if not out:
        out = _heuristic_mutations(symbol, memory_summary, max_specs, seed=seed)
        rationale = f"{rationale} (fallback heuristics)"
    return rationale, out