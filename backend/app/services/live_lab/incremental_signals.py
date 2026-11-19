"""Discover new strategy orders at the latest closed bar only (no lookahead)."""

from __future__ import annotations

from app.backtest.bars import Bar
from app.backtest.berg_tnb.pipeline import BergTnbEngine
from app.backtest.video_strategies import VideoConfig, anchor_bos_orders, session_sweep_orders
from app.services.market_data.sessions import session_keys_for_bars


def discover_video_orders(spec: dict, bars: list[Bar], instrument, *, at_index: int) -> list:
    if at_index < 1 or at_index >= len(bars):
        return []
    entry = (spec.get("entry") or {}).get("type", "")
    cfg = VideoConfig.from_instrument(instrument, spec)
    session_keys = session_keys_for_bars(
        bars[: at_index + 1],
        spec,
        instrument_trading_hours=getattr(instrument, "trading_hours", None) or {},
    )
    if entry == "video_liquidity_sweep":
        orders = session_sweep_orders(bars[: at_index + 1], cfg, session_keys)
    elif entry == "video_anchor_bos":
        orders = anchor_bos_orders(bars[: at_index + 1], cfg)
    else:
        return []
    return [o for o in orders if o.signal_index == at_index]


def discover_berg_orders(spec: dict, bars_5m: list[Bar], instrument, *, at_index: int) -> list:
    if at_index < 1:
        return []
    engine = BergTnbEngine(spec, bars_5m[: at_index + 1], instrument.tick_size)
    _setups, orders, _events, _rej = engine.run()
    return [o for o in orders if o.signal_index == at_index]