"""Discover new strategy orders at the latest closed bar only (no lookahead)."""

from __future__ import annotations

from app.backtest.bars import Bar
from app.backtest.berg_tnb.pipeline import BergTnbEngine
from app.backtest.video_incremental import (
    AnchorBosRuntime,
    SessionSweepRuntime,
    anchor_bos_step,
    session_sweep_step,
)
from app.backtest.video_strategies import VideoConfig
from app.services.market_data.sessions import session_keys_for_bars


def discover_video_orders(
    spec: dict,
    bars: list[Bar],
    instrument,
    *,
    at_index: int,
    video_runtime: dict | None = None,
) -> tuple[list, dict]:
    if at_index < 0 or at_index >= len(bars):
        return [], video_runtime or {}
    entry = (spec.get("entry") or {}).get("type", "")
    cfg = VideoConfig.from_instrument(instrument, spec)
    session_keys = session_keys_for_bars(
        bars,
        spec,
        instrument_trading_hours=getattr(instrument, "trading_hours", None) or {},
    )
    vr = dict(video_runtime or {})
    if entry == "video_liquidity_sweep":
        rt = SessionSweepRuntime.from_dict(vr.get("session_sweep"))
        rt, orders = session_sweep_step(rt, bars, cfg, session_keys, at_index)
        vr["session_sweep"] = rt.to_dict()
        vr["engine"] = "video_liquidity_sweep_incremental_v1"
    elif entry == "video_anchor_bos":
        rt = AnchorBosRuntime.from_dict(vr.get("anchor_bos"))
        rt, orders = anchor_bos_step(rt, bars, cfg, at_index)
        vr["anchor_bos"] = rt.to_dict()
        vr["engine"] = "video_anchor_bos_incremental_v1"
    else:
        return [], vr
    return orders, vr


def discover_berg_orders(
    spec: dict,
    bars_5m: list[Bar],
    instrument,
    *,
    at_index: int,
    bars_4h: list[Bar] | None = None,
    runtime: dict | None = None,
) -> tuple[list, dict, list]:
    from app.services.live_lab.berg_forward import BergForwardRuntime, berg_forward_step

    rt = BergForwardRuntime.from_dict(runtime)
    bars_4h = bars_4h or []
    if len(bars_5m) <= at_index:
        return [], rt.to_dict(), []
    if at_index != len(bars_5m) - 1:
        return [], rt.to_dict(), []
    rt, orders, amendments, _ = berg_forward_step(rt, spec, bars_5m, bars_4h, instrument.tick_size)
    return orders, rt.to_dict(), amendments