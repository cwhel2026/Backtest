"""Generate strategy hypotheses — OpenAI when configured, else deterministic heuristic."""

import json
import re
from typing import Any

import httpx

from app.backtest.dsl import ENTRY_TYPES, SUPPORTED_TIMEFRAMES, validate_spec
from app.core.config import get_settings

DSL_HINT = """
Return JSON only with this shape:
{
  "economic_rationale": "1-3 sentences",
  "specification": {
    "name": "string",
    "instrument_symbol": "MES",
    "timeframe": "5m",
    "category": "snake_case",
    "session": {"allowed": ["RTH"], "timezone": "America/Chicago"},
    "entry": {"type": "ema_crossover|ema_pullback|mtf_ema_pullback|opening_range_breakout|vwap_reversion|rsi_reversion|donchian_breakout|consecutive_closes|fair_value_gap|bollinger_reversion|liquidity_sweep|order_block_retest|premium_discount", "...params", "invert": false},
    "filters": {"start_hhmm": "08:30", "end_hhmm": "11:00", "vwap_align": "with|against", "htf": "15m", "htf_ema": 21, "atr_min_ticks": 6, "max_trades_per_day": 2},
    "exit": {"stop_ticks": int, "target_ticks": int, "stop_atr": 1.5, "target_atr": 2.0, "breakeven_r": 1.0, "trail_atr": 1.0, "max_bars": 18, "session_end_flatten": true},
    "risk": {"dollar_risk_per_trade": number, "max_contracts": int}
  }
}
entry types: ema_crossover (fast_period, slow_period), opening_range_breakout (range_minutes, side),
vwap_reversion (deviation_ticks), rsi_reversion (period, oversold, overbought),
donchian_breakout (lookback), consecutive_closes (count),
fair_value_gap (min_gap_ticks, max_age_bars, side), bollinger_reversion (period, std_mult),
liquidity_sweep (lookback, sweep_ticks), ema_pullback (fast_period, slow_period),
order_block_retest, premium_discount, mtf_ema_pullback. invert=true fades.
Prefer filters (NY morning window, VWAP/HTF alignment) and ATR/trail/time-stop exits over raw tick grids.
timeframes: 1m, 5m, 15m, 1h only.
"""


def _heuristic_generate(instrument_symbol: str, timeframe: str, prompt: str) -> tuple[str, dict]:
    text = prompt.lower()
    symbol = instrument_symbol.upper()
    if timeframe not in SUPPORTED_TIMEFRAMES:
        timeframe = "5m"

    if "rsi" in text.split() or "rsi" in text.replace("-", " ").split():
        entry_type = "rsi_reversion"
        category = "rsi_reversion"
        entry = {"type": entry_type, "period": 14, "oversold": 30, "overbought": 70}
        rationale = f"Heuristic: RSI stretch mean-reversion on {symbol}."
    elif any(w in text for w in ("donchian", "channel", "turtle")):
        entry_type = "donchian_breakout"
        category = "donchian_breakout"
        entry = {"type": entry_type, "lookback": 20}
        rationale = f"Heuristic: Donchian breakout on {symbol}."
    elif any(w in text for w in ("vwap", "reversion", "mean revert", "fade")):
        entry_type = "vwap_reversion"
        category = "vwap_mean_reversion"
        entry = {"type": entry_type, "deviation_ticks": 16}
        rationale = f"Heuristic: session VWAP stretch on {symbol} may revert during liquid hours."
    elif any(w in text for w in ("orb", "opening", "range", "breakout")):
        entry_type = "opening_range_breakout"
        category = "opening_range_breakout"
        entry = {"type": entry_type, "range_minutes": 15, "side": "both"}
        rationale = f"Heuristic: RTH opening range breakout on {symbol} ({prompt[:120]})."
    else:
        entry_type = "ema_crossover"
        category = "trend_continuation"
        fast, slow = 8, 21
        m = re.search(r"(\d+)\s*/\s*(\d+)", prompt)
        if m:
            fast, slow = int(m.group(1)), int(m.group(2))
        entry = {"type": entry_type, "fast_period": fast, "slow_period": slow}
        rationale = f"Heuristic: EMA momentum on {symbol} ({prompt[:120]})."

    stop = 20 if "micro" in symbol.lower() or symbol.startswith("M") else 16
    target = 32 if stop >= 20 else 24
    spec = {
        "name": f"{symbol} {timeframe} {category.replace('_', ' ').title()}",
        "instrument_symbol": symbol,
        "timeframe": timeframe,
        "category": category,
        "session": {"allowed": ["RTH"], "timezone": "America/Chicago"},
        "entry": entry,
        "exit": {"stop_ticks": stop, "target_ticks": target, "session_end_flatten": True},
        "risk": {"dollar_risk_per_trade": 75, "max_contracts": 3},
    }
    if prompt.strip():
        rationale = f"{rationale} User note: {prompt.strip()[:240]}"
    return rationale, spec


def _parse_openai_json(content: str) -> dict[str, Any]:
    return json.loads(content)


def generate_hypothesis_and_spec(
    instrument_symbol: str,
    timeframe: str,
    prompt: str,
) -> tuple[str, dict]:
    settings = get_settings()
    if not settings.ai_configured:
        return _heuristic_generate(instrument_symbol, timeframe, prompt)

    model = getattr(settings, "openai_model", None) or "gpt-4o-mini"
    user_msg = (
        f"Instrument: {instrument_symbol}\nTimeframe: {timeframe}\nResearch idea:\n{prompt}\n\n{DSL_HINT}"
    )
    try:
        with httpx.Client(timeout=90.0) as client:
            resp = client.post(
                "https://api.openai.com/v1/chat/completions",
                headers={
                    "Authorization": f"Bearer {settings.openai_api_key.strip()}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": model,
                    "response_format": {"type": "json_object"},
                    "messages": [
                        {
                            "role": "system",
                            "content": "You are a CME futures quant researcher. Output only valid JSON matching the schema.",
                        },
                        {"role": "user", "content": user_msg},
                    ],
                    "temperature": 0.4,
                },
            )
        resp.raise_for_status()
        data = resp.json()
        content = data["choices"][0]["message"]["content"]
        parsed = _parse_openai_json(content)
        rationale = str(parsed.get("economic_rationale", prompt))
        spec = parsed.get("specification") or parsed
        if "entry" not in spec:
            raise ValueError("OpenAI response missing specification.entry")
        spec.setdefault("instrument_symbol", instrument_symbol.upper())
        spec.setdefault("timeframe", timeframe)
        errors = validate_spec(spec)
        if errors:
            raise ValueError(f"AI spec invalid: {'; '.join(errors)}")
        if spec["entry"]["type"] not in ENTRY_TYPES:
            raise ValueError("Unsupported entry type from AI")
        return rationale, spec
    except Exception:
        return _heuristic_generate(instrument_symbol, timeframe, prompt)