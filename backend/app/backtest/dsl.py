"""Declarative strategy DSL — no arbitrary code execution."""

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Any
from zoneinfo import ZoneInfo

from app.backtest.bars import Bar
from app.backtest.fvg import discover_fvg_zones, fvg_retest_signal
from app.backtest.ict import (
    discover_order_blocks,
    order_block_retest,
    range_position,
    session_dealing_ranges,
)
from app.backtest.indicators import atr_series, bollinger_series, ema_series, rsi_series, session_vwap
from app.backtest.mtf import htf_bars_from_ltf, ltf_to_htf_index, series_on_ltf
from app.backtest.structure import (
    anchor_limit_price,
    confirmed_swings,
    detect_anchor_bos_retrace,
    detect_liquidity_sweep_reversal,
    sweep_limit_price,
)


@dataclass
class EntrySignal:
    direction: str  # long | short
    signal_ts: datetime
    stop_price: Decimal
    target_price: Decimal
    reason: str
    entry_mode: str = "market"  # market | limit
    limit_price: Decimal | None = None
    order_expire_bars: int = 12
    setup_meta: dict | None = None


ENTRY_TYPES = frozenset(
    {
        "opening_range_breakout",
        "ema_crossover",
        "ema_pullback",
        "vwap_reversion",
        "rsi_reversion",
        "donchian_breakout",
        "consecutive_closes",
        "fair_value_gap",
        "bollinger_reversion",
        "liquidity_sweep",
        "liquidity_sweep_reversal",
        "anchor_bos_retrace",
        "sweep_bos_combined",
        "video_liquidity_sweep",
        "video_anchor_bos",
        "order_block_retest",
        "premium_discount",
        "mtf_ema_pullback",
        "confluence",
    }
)
PRIMITIVE_ENTRY_TYPES = frozenset(t for t in ENTRY_TYPES if t != "confluence")
SUPPORTED_TIMEFRAMES = frozenset({"1m", "5m", "15m", "30m", "1h"})


def confluence_legs(entry: dict[str, Any]) -> list[dict[str, Any]]:
    raw = entry.get("all") if entry.get("all") is not None else entry.get("legs")
    if not isinstance(raw, list):
        return []
    return [leg for leg in raw if isinstance(leg, dict)]


def validate_spec(spec: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    for key in ("name", "instrument_symbol", "timeframe", "entry", "exit", "risk"):
        if key not in spec:
            errors.append(f"Missing {key}")
    if spec.get("timeframe") not in SUPPORTED_TIMEFRAMES:
        errors.append(f"timeframe must be one of {sorted(SUPPORTED_TIMEFRAMES)}")
    entry = spec.get("entry") or {}
    if "type" not in entry:
        errors.append("entry.type required")
    elif entry.get("type") not in ENTRY_TYPES:
        errors.append(f"entry.type must be one of {sorted(ENTRY_TYPES)}")
    elif entry.get("type") == "confluence":
        legs = confluence_legs(entry)
        if not (2 <= len(legs) <= 3):
            errors.append("confluence entry.all must contain 2 or 3 primitive setups")
        for i, leg in enumerate(legs):
            lt = leg.get("type")
            if lt not in PRIMITIVE_ENTRY_TYPES:
                errors.append(f"confluence leg {i} type must be a primitive entry, not {lt!r}")
    exit_spec = spec.get("exit") or {}
    if "stop_ticks" not in exit_spec or "target_ticks" not in exit_spec:
        errors.append("exit.stop_ticks and exit.target_ticks required")
    entry_type = entry.get("type")
    if entry_type in ("video_liquidity_sweep", "video_anchor_bos"):
        fib = Decimal(str(entry.get("fib_ratio", "0.618")))
        if not (Decimal("0") < fib < Decimal("1")):
            errors.append("entry.fib_ratio must be between 0 and 1 (default 0.618; alternatives e.g. 0.595 are config-only)")
    return errors


def session_keys_rth(bars: list[Bar], tz: str = "America/Chicago", instrument_trading_hours: dict | None = None) -> list[str]:
    from app.services.market_data.sessions import session_keys_rth_calendar

    return session_keys_rth_calendar(bars, tz=tz, instrument_trading_hours=instrument_trading_hours)


def opening_range_bounds(
    bars: list[Bar], session_keys: list[str], range_minutes: int, tz: str = "America/Chicago"
) -> dict[str, tuple[Decimal, Decimal, int]]:
    """Per session: (or_high, or_low, last_or_bar_index)."""
    zone = ZoneInfo(tz)
    open_minutes = 8 * 60 + 30
    out: dict[str, tuple[Decimal, Decimal, int]] = {}
    for i, b in enumerate(bars):
        local = b.ts.astimezone(zone)
        mins = local.hour * 60 + local.minute
        offset = mins - open_minutes
        if offset < 0 or offset >= range_minutes:
            continue
        key = session_keys[i]
        if key in out:
            hi = max(b.high, out[key][0])
            lo = min(b.low, out[key][1])
        else:
            hi, lo = b.high, b.low
        out[key] = (hi, lo, i)
    return out


@dataclass
class SignalContext:
    """Precomputed indicator series for O(n) per-bar signal evaluation."""

    session_keys: list[str]
    or_map: dict[str, tuple[Decimal, Decimal, int]] | None = None
    fast_e: list[Decimal | None] | None = None
    slow_e: list[Decimal | None] | None = None
    vwap: list[Decimal | None] | None = None
    rsi: list[Decimal | None] | None = None
    fvg_zones: list | None = None
    bb_upper: list[Decimal | None] | None = None
    bb_lower: list[Decimal | None] | None = None
    session_ranges: dict | None = None
    order_blocks: list | None = None
    htf_fast_ltf: list[Decimal | None] | None = None
    htf_slow_ltf: list[Decimal | None] | None = None
    atr: list[Decimal | None] | None = None
    filter_htf_ema: list[Decimal | None] | None = None
    leg_contexts: list["SignalContext"] | None = None
    swings: list | None = None


def build_signal_context(
    spec: dict,
    bars: list[Bar],
    session_keys: list[str] | None = None,
    *,
    instrument_tick: Decimal | None = None,
) -> SignalContext:
    """Compute indicators once per backtest (avoids O(n²) prefix recomputation)."""
    if session_keys is None:
        session_keys = session_keys_rth(bars)
    entry = spec["entry"]
    entry_type = entry.get("type")
    ctx = SignalContext(session_keys=session_keys)
    if entry_type == "opening_range_breakout":
        range_minutes = int(entry.get("range_minutes", 15))
        ctx.or_map = opening_range_bounds(bars, session_keys, range_minutes)
    elif entry_type in ("ema_crossover", "ema_pullback"):
        closes = [b.close for b in bars]
        fast = int(entry.get("fast_period", 9))
        slow = int(entry.get("slow_period", 21))
        ctx.fast_e = ema_series(closes, fast)
        ctx.slow_e = ema_series(closes, slow)
    elif entry_type == "fair_value_gap":
        min_gap = int(entry.get("min_gap_ticks", 4))
        tick = instrument_tick or Decimal("0.25")
        ctx.fvg_zones = discover_fvg_zones(bars, instrument_tick=tick, min_gap_ticks=min_gap)
    elif entry_type == "bollinger_reversion":
        closes = [b.close for b in bars]
        period = int(entry.get("period", 20))
        mult = Decimal(str(entry.get("std_mult", 2)))
        _mid, upper, lower = bollinger_series(closes, period, mult)
        ctx.bb_upper = upper
        ctx.bb_lower = lower
    elif entry_type == "vwap_reversion":
        ctx.vwap = session_vwap(bars, session_keys)
    elif entry_type == "rsi_reversion":
        closes = [b.close for b in bars]
        period = int(entry.get("period", 14))
        ctx.rsi = rsi_series(closes, period)
    elif entry_type == "order_block_retest":
        tick = instrument_tick or Decimal("0.25")
        disp = int(entry.get("displacement_ticks", 12))
        ctx.order_blocks = discover_order_blocks(bars, instrument_tick=tick, displacement_ticks=disp)
    elif entry_type == "premium_discount":
        ctx.session_ranges = session_dealing_ranges(bars, session_keys)
    elif entry_type == "mtf_ema_pullback":
        htf = str(entry.get("htf", "15m"))
        fast = int(entry.get("fast_period", 9))
        slow = int(entry.get("slow_period", 21))
        htf_bars = htf_bars_from_ltf(bars, htf)
        idx = ltf_to_htf_index(bars, htf_bars)
        closes_htf = [b.close for b in htf_bars]
        ctx.htf_fast_ltf = series_on_ltf(ema_series(closes_htf, fast), idx)
        ctx.htf_slow_ltf = series_on_ltf(ema_series(closes_htf, slow), idx)
        closes = [b.close for b in bars]
        ctx.fast_e = ema_series(closes, fast)
        ctx.slow_e = ema_series(closes, slow)
    elif entry_type == "confluence":
        ctx.leg_contexts = []
        for leg in confluence_legs(entry):
            leg_spec = {**spec, "entry": {**leg, "invert": False}, "filters": {}}
            ctx.leg_contexts.append(
                build_signal_context(leg_spec, bars, session_keys, instrument_tick=instrument_tick)
            )

    filters = spec.get("filters") or {}
    exit_spec = spec.get("exit") or {}
    needs_atr = any(
        exit_spec.get(k) is not None for k in ("stop_atr", "target_atr", "trail_atr")
    ) or filters.get("atr_min_ticks") is not None or filters.get("atr_max_ticks") is not None
    if needs_atr:
        period = int(exit_spec.get("atr_period") or filters.get("atr_period") or 14)
        ctx.atr = atr_series(bars, period)
    if filters.get("vwap_align") and ctx.vwap is None:
        ctx.vwap = session_vwap(bars, session_keys)
    if filters.get("htf"):
        htf = str(filters.get("htf") or "15m")
        period = int(filters.get("htf_ema") or 21)
        htf_bars = htf_bars_from_ltf(bars, htf)
        idx = ltf_to_htf_index(bars, htf_bars)
        ctx.filter_htf_ema = series_on_ltf(ema_series([b.close for b in htf_bars], period), idx)
    if entry_type in ("liquidity_sweep_reversal", "anchor_bos_retrace", "sweep_bos_combined"):
        left = int(entry.get("swing_left", 2))
        right = int(entry.get("swing_right", 2))
        ctx.swings = confirmed_swings(bars, left=left, right=right)
    return ctx


def _pack_signal(
    *,
    direction: str,
    ts: datetime,
    entry_px: Decimal,
    stop_ticks: int,
    target_ticks: int,
    tick: Decimal,
    reason: str,
    invert: bool,
    target_override: Decimal | None = None,
) -> EntrySignal:
    if invert:
        direction = "short" if direction == "long" else "long"
        reason = f"rev_{reason}"
        target_override = None
    if direction == "long":
        stop = entry_px - stop_ticks * tick
        target = target_override if target_override is not None else entry_px + target_ticks * tick
    else:
        stop = entry_px + stop_ticks * tick
        target = target_override if target_override is not None else entry_px - target_ticks * tick
    return EntrySignal(direction, ts, stop, target, reason)


def _hhmm_minutes(value: object) -> int | None:
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    parts = text.split(":")
    try:
        hour = int(parts[0])
        minute = int(parts[1]) if len(parts) > 1 else 0
    except (TypeError, ValueError):
        return None
    return hour * 60 + minute


def _apply_filters(
    spec: dict,
    bars: list[Bar],
    i: int,
    ctx: SignalContext,
    tick: Decimal,
    sig: EntrySignal,
) -> EntrySignal | None:
    filters = spec.get("filters") or {}
    if not filters:
        return sig
    bar = bars[i]
    tz_name = str((spec.get("session") or {}).get("timezone") or "America/Chicago")
    local = bar.ts.astimezone(ZoneInfo(tz_name))
    mins = local.hour * 60 + local.minute
    start = _hhmm_minutes(filters.get("start_hhmm"))
    end = _hhmm_minutes(filters.get("end_hhmm"))
    if start is not None and mins < start:
        return None
    if end is not None and mins >= end:
        return None

    if ctx.atr is not None and (filters.get("atr_min_ticks") is not None or filters.get("atr_max_ticks") is not None):
        atr = ctx.atr[i]
        if atr is None or tick <= 0:
            return None
        atr_ticks = atr / tick
        min_ticks = filters.get("atr_min_ticks")
        max_ticks = filters.get("atr_max_ticks")
        if min_ticks is not None and atr_ticks < Decimal(str(min_ticks)):
            return None
        if max_ticks is not None and atr_ticks > Decimal(str(max_ticks)):
            return None

    align = filters.get("vwap_align")
    if align and ctx.vwap is not None:
        vwap = ctx.vwap[i]
        if vwap is None:
            return None
        above = bar.close >= vwap
        if align == "with":
            if sig.direction == "long" and not above:
                return None
            if sig.direction == "short" and above:
                return None
        elif align == "against":
            if sig.direction == "long" and above:
                return None
            if sig.direction == "short" and not above:
                return None

    if filters.get("htf") and ctx.filter_htf_ema is not None:
        ema = ctx.filter_htf_ema[i]
        if ema is None:
            return None
        up = bar.close >= ema
        if sig.direction == "long" and not up:
            return None
        if sig.direction == "short" and up:
            return None
    return sig


def signal_at_bar(
    spec: dict,
    bars: list[Bar],
    i: int,
    session_keys: list[str],
    instrument_tick: Decimal,
    ctx: SignalContext | None = None,
) -> EntrySignal | None:
    """Evaluate signal using data through bar index i (completed bar)."""
    if ctx is None:
        ctx = build_signal_context(spec, bars, session_keys)
    entry = spec["entry"]
    exit_spec = spec["exit"]
    entry_type = entry.get("type")
    stop_ticks = int(exit_spec.get("stop_ticks", 8))
    target_ticks = int(exit_spec.get("target_ticks", 16))
    invert = bool(entry.get("invert"))
    bar = bars[i]
    tick = instrument_tick

    def pack(direction: str, reason: str, target_override: Decimal | None = None) -> EntrySignal | None:
        sig = _pack_signal(
            direction=direction,
            ts=bar.ts,
            entry_px=bar.close,
            stop_ticks=stop_ticks,
            target_ticks=target_ticks,
            tick=tick,
            reason=reason,
            invert=invert,
            target_override=target_override,
        )
        return _apply_filters(spec, bars, i, ctx, tick, sig)

    if entry_type == "ema_crossover":
        fast_e = ctx.fast_e
        slow_e = ctx.slow_e
        if fast_e is None or slow_e is None:
            raise ValueError("SignalContext missing EMA series")
        if fast_e[i] is None or slow_e[i] is None or i < 1:
            return None
        if fast_e[i - 1] is None or slow_e[i - 1] is None:
            return None
        crossed_up = fast_e[i - 1] <= slow_e[i - 1] and fast_e[i] > slow_e[i]
        crossed_dn = fast_e[i - 1] >= slow_e[i - 1] and fast_e[i] < slow_e[i]
        if crossed_up:
            return pack("long", "ema_cross_up")
        if crossed_dn:
            return pack("short", "ema_cross_down")
        return None

    if entry_type == "opening_range_breakout":
        or_map = ctx.or_map
        if or_map is None:
            raise ValueError("SignalContext missing opening range map")
        key = session_keys[i]
        if key not in or_map:
            return None
        or_high, or_low, last_or = or_map[key]
        if i <= last_or:
            return None
        side = entry.get("side", "both")
        if side in ("both", "long") and bar.close > or_high:
            return pack("long", "or_breakout_long")
        if side in ("both", "short") and bar.close < or_low:
            return pack("short", "or_breakout_short")
        return None

    if entry_type == "vwap_reversion":
        dev_ticks = Decimal(str(entry.get("deviation_ticks", 12)))
        vwap = ctx.vwap
        if vwap is None:
            raise ValueError("SignalContext missing VWAP series")
        if vwap[i] is None:
            return None
        if bar.close >= vwap[i] + dev_ticks * tick:
            return pack("short", "vwap_stretch_short", None if invert else vwap[i])
        if bar.close <= vwap[i] - dev_ticks * tick:
            return pack("long", "vwap_stretch_long", None if invert else vwap[i])
        return None

    if entry_type == "rsi_reversion":
        oversold = Decimal(str(entry.get("oversold", 30)))
        overbought = Decimal(str(entry.get("overbought", 70)))
        series = ctx.rsi
        if series is None:
            raise ValueError("SignalContext missing RSI series")
        if series[i] is None or i < 1 or series[i - 1] is None:
            return None
        rsi_now = series[i]
        rsi_prev = series[i - 1]
        assert rsi_now is not None and rsi_prev is not None
        if rsi_prev >= oversold and rsi_now < oversold:
            return pack("long", "rsi_oversold")
        if rsi_prev <= overbought and rsi_now > overbought:
            return pack("short", "rsi_overbought")
        return None

    if entry_type == "donchian_breakout":
        lookback = int(entry.get("lookback", 20))
        if i < lookback:
            return None
        window = bars[i - lookback : i]
        highest = max(b.high for b in window)
        lowest = min(b.low for b in window)
        if bar.close > highest:
            return pack("long", "donchian_break_high")
        if bar.close < lowest:
            return pack("short", "donchian_break_low")
        return None

    if entry_type == "consecutive_closes":
        count = int(entry.get("count", 3))
        if i < count:
            return None
        ups = all(bars[i - k].close > bars[i - k - 1].close for k in range(count))
        dns = all(bars[i - k].close < bars[i - k - 1].close for k in range(count))
        if ups:
            return pack("long", "streak_up")
        if dns:
            return pack("short", "streak_down")
        return None

    if entry_type == "fair_value_gap":
        zones = ctx.fvg_zones
        if not zones:
            return None
        max_age = int(entry.get("max_age_bars", 48))
        side = str(entry.get("side", "both"))
        direction = fvg_retest_signal(bar, i, zones, max_age_bars=max_age, side=side)
        if direction == "long":
            return pack("long", "fvg_retest_long")
        if direction == "short":
            return pack("short", "fvg_retest_short")
        return None

    if entry_type == "bollinger_reversion":
        upper = ctx.bb_upper
        lower = ctx.bb_lower
        if upper is None or lower is None or upper[i] is None or lower[i] is None:
            return None
        if i < 1:
            return None
        touch_hi = bar.high >= upper[i]
        touch_lo = bar.low <= lower[i]
        if touch_hi and bar.close < upper[i]:
            return pack("short", "bb_upper_reject")
        if touch_lo and bar.close > lower[i]:
            return pack("long", "bb_lower_reject")
        return None

    if entry_type == "ema_pullback":
        fast_e = ctx.fast_e
        slow_e = ctx.slow_e
        if fast_e is None or slow_e is None or fast_e[i] is None or slow_e[i] is None or i < 2:
            return None
        if fast_e[i - 1] is None or slow_e[i - 1] is None:
            return None
        uptrend = fast_e[i - 1] > slow_e[i - 1]
        dntrend = fast_e[i - 1] < slow_e[i - 1]
        ema_px = fast_e[i]
        assert ema_px is not None
        if uptrend and bar.low <= ema_px <= bar.high and bar.close > ema_px:
            return pack("long", "ema_pullback_long")
        if dntrend and bar.low <= ema_px <= bar.high and bar.close < ema_px:
            return pack("short", "ema_pullback_short")
        return None

    if entry_type == "liquidity_sweep":
        lookback = int(entry.get("lookback", 12))
        sweep_ticks = int(entry.get("sweep_ticks", 2))
        if i < lookback + 1:
            return None
        window = bars[i - lookback : i]
        swing_hi = max(b.high for b in window)
        swing_lo = min(b.low for b in window)
        sweep = tick * Decimal(sweep_ticks)
        if bar.low < swing_lo - sweep and bar.close > swing_lo:
            return pack("long", "liq_sweep_low")
        if bar.high > swing_hi + sweep and bar.close < swing_hi:
            return pack("short", "liq_sweep_high")
        return None

    if entry_type == "liquidity_sweep_reversal":
        sweep_ticks = int(entry.get("sweep_ticks", 2))
        fib_ratio = Decimal(str(entry.get("fib_ratio", "0.618")))
        buffer_ticks = int(entry.get("stop_buffer_ticks", 2))
        rr = Decimal(str(entry.get("reward_risk", "2")))
        require_bos = bool(entry.get("require_bos", False))
        setup = detect_liquidity_sweep_reversal(
            bars,
            i,
            session_keys,
            tick,
            sweep_ticks=sweep_ticks,
            fib_ratio=fib_ratio,
            require_bos=require_bos,
            swings=ctx.swings,
        )
        if not setup:
            return None
        limit = sweep_limit_price(setup, fib_ratio)
        if setup.direction == "long":
            stop = setup.sweep_extreme - tick * Decimal(buffer_ticks)
            target = limit + (limit - stop) * rr
        else:
            stop = setup.sweep_extreme + tick * Decimal(buffer_ticks)
            target = limit - (stop - limit) * rr
        sig = EntrySignal(
            setup.direction,
            setup.signal_ts,
            stop,
            target,
            setup.reason,
            entry_mode="limit",
            limit_price=limit,
            order_expire_bars=int(entry.get("order_expire_bars", 12)),
            setup_meta={"strategy": "liquidity_sweep_reversal", "reclaimed": str(setup.reclaimed_level)},
        )
        return _apply_filters(spec, bars, i, ctx, tick, sig)

    if entry_type == "anchor_bos_retrace":
        if not ctx.swings:
            return None
        setup = detect_anchor_bos_retrace(
            bars,
            i,
            ctx.swings,
            require_close_confirm=bool(entry.get("close_confirm", True)),
        )
        if not setup:
            return None
        fib_ratio = Decimal(str(entry.get("fib_ratio", "0.618")))
        buffer_ticks = int(entry.get("stop_buffer_ticks", 2))
        rr = Decimal(str(entry.get("reward_risk", "2")))
        limit = anchor_limit_price(setup, fib_ratio)
        if setup.direction == "long":
            stop = setup.impulse_low - tick * Decimal(buffer_ticks)
            target = limit + (limit - stop) * rr
        else:
            stop = setup.impulse_high + tick * Decimal(buffer_ticks)
            target = limit - (stop - limit) * rr
        sig = EntrySignal(
            setup.direction,
            setup.signal_ts,
            stop,
            target,
            setup.reason,
            entry_mode="limit",
            limit_price=limit,
            order_expire_bars=int(entry.get("order_expire_bars", 16)),
            setup_meta={
                "strategy": "anchor_bos_retrace",
                "anchor_confirmed_at": setup.anchor.confirmed_at,
            },
        )
        return _apply_filters(spec, bars, i, ctx, tick, sig)

    if entry_type == "sweep_bos_combined":
        sweep_ticks = int(entry.get("sweep_ticks", 2))
        max_bars_between = int(entry.get("max_bars_between", 6))
        fib_ratio = Decimal(str(entry.get("fib_ratio", "0.618")))
        min_rr = Decimal(str(entry.get("min_reward_risk", "1.5")))
        a = detect_liquidity_sweep_reversal(
            bars,
            i,
            session_keys,
            tick,
            sweep_ticks=sweep_ticks,
            require_bos=True,
            swings=ctx.swings,
        )
        if not a:
            return None
        found_bos = False
        bos_dir = a.direction
        for lag in range(1, max_bars_between + 1):
            j = i - lag
            if j < 0 or not ctx.swings:
                break
            bsetup = detect_anchor_bos_retrace(bars, j, ctx.swings, require_close_confirm=True)
            if bsetup and bsetup.direction == bos_dir:
                found_bos = True
                break
        if not found_bos:
            return None
        limit = sweep_limit_price(a, fib_ratio)
        buffer_ticks = int(entry.get("stop_buffer_ticks", 2))
        if a.direction == "long":
            stop = a.sweep_extreme - tick * Decimal(buffer_ticks)
            risk = limit - stop
            if risk <= 0:
                return None
            target = limit + risk * min_rr
        else:
            stop = a.sweep_extreme + tick * Decimal(buffer_ticks)
            risk = stop - limit
            if risk <= 0:
                return None
            target = limit - risk * min_rr
        sig = EntrySignal(
            a.direction,
            a.signal_ts,
            stop,
            target,
            "sweep_bos_combined",
            entry_mode="limit",
            limit_price=limit,
            order_expire_bars=int(entry.get("order_expire_bars", 12)),
            setup_meta={"strategy": "sweep_bos_combined"},
        )
        return _apply_filters(spec, bars, i, ctx, tick, sig)

    if entry_type == "order_block_retest":
        zones = ctx.order_blocks
        if not zones:
            return None
        max_age = int(entry.get("max_age_bars", 60))
        side = str(entry.get("side", "both"))
        direction = order_block_retest(bar, i, zones, max_age_bars=max_age, side=side)
        if direction == "long":
            return pack("long", "ob_retest_long")
        if direction == "short":
            return pack("short", "ob_retest_short")
        return None

    if entry_type == "premium_discount":
        ranges = ctx.session_ranges
        if not ranges:
            return None
        key = session_keys[i]
        sr = ranges.get(key)
        if sr is None:
            return None
        pos = range_position(bar.close, sr)
        discount_max = Decimal(str(entry.get("discount_max", 0.38)))
        premium_min = Decimal(str(entry.get("premium_min", 0.62)))
        zone = str(entry.get("zone", "both"))
        if zone in ("both", "discount") and pos <= discount_max and bar.close > bar.open:
            return pack("long", "discount_bounce")
        if zone in ("both", "premium") and pos >= premium_min and bar.close < bar.open:
            return pack("short", "premium_fade")
        return None

    if entry_type == "mtf_ema_pullback":
        hf = ctx.htf_fast_ltf
        hs = ctx.htf_slow_ltf
        fast_e = ctx.fast_e
        if hf is None or hs is None or fast_e is None:
            return None
        if hf[i] is None or hs[i] is None or fast_e[i] is None or i < 1:
            return None
        ema_px = fast_e[i]
        if hf[i] > hs[i] and bar.low <= ema_px <= bar.high and bar.close > ema_px:
            return pack("long", "mtf_pullback_long")
        if hf[i] < hs[i] and bar.low <= ema_px <= bar.high and bar.close < ema_px:
            return pack("short", "mtf_pullback_short")
        return None

    if entry_type == "confluence":
        legs = confluence_legs(entry)
        window = max(0, int(entry.get("window_bars", 2)))
        leg_ctxs = ctx.leg_contexts or []
        if len(legs) < 2 or len(leg_ctxs) != len(legs):
            return None
        directions: list[str] = []
        reasons: list[str] = []
        for leg, lctx in zip(legs, leg_ctxs, strict=True):
            found: EntrySignal | None = None
            for lag in range(window + 1):
                j = i - lag
                if j < 0:
                    break
                lspec = {**spec, "entry": {**leg, "invert": False}, "filters": {}}
                found = signal_at_bar(lspec, bars, j, session_keys, tick, lctx)
                if found:
                    break
            if not found:
                return None
            directions.append(found.direction)
            reasons.append(found.reason)
        if len(set(directions)) != 1:
            return None
        return pack(directions[0], "conf_" + "+".join(reasons))

    raise ValueError(f"Unsupported entry.type {entry_type}")