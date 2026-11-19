"""Live progress blob stored on prop search job payloads for the desk UI."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from app.models.research import ResearchJob

SEARCH_FAMILY_LABELS = (
    "ORB",
    "EMA",
    "EMA pull",
    "VWAP",
    "RSI",
    "Donchian",
    "Streak",
    "FVG",
    "Bollinger",
    "Liquidity",
    "Order block",
    "Premium / discount",
    "MTF pull",
    "ORB VWAP",
    "Killzone FVG",
    "ATR pull",
    "Sweep fade",
    "Sweep+FVG",
    "Sweep+OB",
    "ORB+pull",
)

_ENTRY_FAMILY = {
    "opening_range_breakout": "ORB",
    "ema_crossover": "EMA",
    "vwap_reversion": "VWAP",
    "rsi_reversion": "RSI",
    "donchian_breakout": "Donchian",
    "consecutive_closes": "Streak",
    "fair_value_gap": "FVG",
    "bollinger_reversion": "Bollinger",
    "liquidity_sweep": "Liquidity",
    "ema_pullback": "EMA pull",
    "order_block_retest": "Order block",
    "premium_discount": "Premium / discount",
    "mtf_ema_pullback": "MTF pull",
    "confluence": "Confluence",
}


_CATEGORY_FAMILY = {
    "orb_vwap": "ORB VWAP",
    "killzone_fvg": "Killzone FVG",
    "atr_pullback": "ATR pull",
    "sweep_discount": "Sweep fade",
    "sweep_fvg": "Sweep+FVG",
    "sweep_ob": "Sweep+OB",
    "orb_pull": "ORB+pull",
}


def entry_family_label(spec: dict | None) -> str | None:
    if not spec:
        return None
    cat = str(spec.get("category") or "")
    if cat.startswith("reversed_"):
        base = cat.removeprefix("reversed_")
        return f"Fade {_CATEGORY_FAMILY.get(base) or _ENTRY_FAMILY.get(base, base)}"
    if cat in _CATEGORY_FAMILY:
        return _CATEGORY_FAMILY[cat]
    entry = spec.get("entry") or {}
    etype = entry.get("type")
    if isinstance(etype, str) and etype in _ENTRY_FAMILY:
        return _ENTRY_FAMILY[etype]
    return _ENTRY_FAMILY.get(cat, cat[:24] or None)


def merge_search_progress(job: ResearchJob, **fields: Any) -> dict:
    payload = dict(job.payload or {})
    progress = {**(payload.get("search_progress") or {}), **fields}
    progress["heartbeat_at"] = datetime.now(UTC).isoformat()
    payload["search_progress"] = progress
    payload["heartbeat"] = progress["heartbeat_at"]
    job.payload = payload
    return progress


def initial_search_progress(*, symbols: tuple[str, ...], budget: int, history_days: int) -> dict:
    return {
        "phase": "starting",
        "symbols": list(symbols),
        "symbol_index": 0,
        "current_symbol": None,
        "budget_per_symbol": budget,
        "history_days": history_days,
        "combos_per_symbol": budget,
        "tests_completed": 0,
        "tests_target_estimate": budget * 3,
        "current_setup": None,
        "setup_family": None,
        "scoring_subphase": None,
        "search_families": list(SEARCH_FAMILY_LABELS),
        "walk_forward": "holdout 20% · train gate · multi-fold OOS · research-window screen · expectancy CI · AI rounds",
        "ai_round": 0,
        "ai_specs_proposed": 0,
        "experiments_recorded": 0,
        "markets_loaded": [],
        "winners_saved": 0,
        "symbols_finished": [],
    }