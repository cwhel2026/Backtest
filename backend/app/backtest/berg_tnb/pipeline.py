"""Berg TNB v1 state machine on 5m bars with recorded transitions."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from app.backtest.bars import Bar, aggregate_bars
from app.backtest.berg_tnb.bias_4h import build_4h_bias_series, bias_for_5m_bar
from app.backtest.berg_tnb.exits import resolve_exit_prices
from app.backtest.berg_tnb.fib import (
    fakeout_anchor_extremes,
    fakeout_touched,
    fib_entry_limit,
    fib_fakeout_level,
)
from app.backtest.berg_tnb.fractals import FractalConfig, confirmed_fractals, fractals_visible_at
from app.backtest.berg_tnb.sessions import aggregate_session_extremes, completed_measurement_for_bar, get_profile
from app.backtest.berg_tnb.types import (
    BergTnbSetup,
    BergTnbState,
    Bias4hRecord,
    Bos5mRecord,
    EntryFibRecord,
    FakeoutFibRecord,
    SessionLevelRecord,
    StateTransition,
    SweepRecord,
)
from app.backtest.berg_tnb.fractals import ConfirmedFractal
from app.backtest.video_strategies import Order, round_tick


def _rollover_suppress(bars: list[Bar], tick: Decimal, events: list[dict] | None = None) -> set[int]:
    try:
        from app.backtest.video_strategies import rollover_suppress_indices

        return rollover_suppress_indices(bars, tick, events)
    except ImportError:
        from app.services.market_data.contract_series import detect_rollover_jumps

        suppress: set[int] = set()
        for hit in detect_rollover_jumps(bars, events or [], tick_size=tick):
            suppress.add(int(hit["index"]))
            if int(hit["index"]) > 0:
                suppress.add(int(hit["index"]) - 1)
        threshold = tick * 80
        for i in range(1, len(bars)):
            if abs(bars[i].open - bars[i - 1].close) >= threshold:
                suppress.add(i)
                suppress.add(i - 1)
        return suppress


def _snap(cfg: dict) -> dict:
    return {k: cfg.get(k) for k in sorted(cfg) if k != "data_context"}


def _log(
    setup: BergTnbSetup,
    *,
    ts: datetime,
    frm: BergTnbState,
    to: BergTnbState,
    bar_index: int,
    reason: str,
    evidence: dict | None = None,
    cfg: dict,
) -> None:
    setup.transitions.append(
        StateTransition(ts, frm, to, bar_index, reason, evidence or {}, _snap(cfg))
    )
    setup.final_state = to


def _candle_dir(o: Decimal, c: Decimal, doji_mode: str) -> str | None:
    if c > o:
        return "bullish"
    if c < o:
        return "bearish"
    if doji_mode == "bullish_doji":
        return "bullish"
    if doji_mode == "bearish_doji":
        return "bearish"
    return None


def _body_close_bos(b: Bar, level: Decimal, direction: str) -> bool:
    """PDF: wick through level is NOT BOS — candle body must close beyond fractal."""
    if direction == "bullish":
        return b.close > level
    return b.close < level


def _bos_after_fakeout(
    bars: list[Bar],
    fractals,
    i: int,
    bias: str,
) -> tuple[bool, ConfirmedFractal | None]:
    if i < 1:
        return False, None
    vis = fractals_visible_at(fractals, i)
    b = bars[i]
    if bias == "bullish":
        highs = [f for f in vis if f.kind == "high"]
        if not highs:
            return False, None
        level = highs[-1].level
        if _body_close_bos(b, level, "bullish") and bars[i - 1].close <= level:
            return True, highs[-1]
    else:
        lows = [f for f in vis if f.kind == "low"]
        if not lows:
            return False, None
        level = lows[-1].level
        if _body_close_bos(b, level, "bearish") and bars[i - 1].close >= level:
            return True, lows[-1]
    return False, None


class BergTnbEngine:
    def __init__(self, spec: dict, bars_5m: list[Bar], instrument_tick: Decimal):
        self.spec = spec
        self.bars = bars_5m
        self.tick = instrument_tick
        entry = spec.get("entry") or {}
        self.cfg = {
            "strategy_id": "berg_tnb_model_v1",
            "session_profile": entry.get("session_profile", "pdf_indices"),
            "setup_preset": entry.get("setup_preset", "new_york_setup"),
            "fractal_4h_left": int(entry.get("fractal_4h_left", 2)),
            "fractal_4h_right": int(entry.get("fractal_4h_right", 2)),
            "fractal_5m_left": int(entry.get("fractal_5m_left", 2)),
            "fractal_5m_right": int(entry.get("fractal_5m_right", 2)),
            "fib_fakeout_ratio": str(entry.get("fib_fakeout_ratio", "0.079")),
            "entry_fib_ratio": str(entry.get("entry_fib_ratio", "0.618")),
            "doji_mode": entry.get("doji_mode", "skip"),
            "allow_exact_sweep_touch": bool(entry.get("allow_exact_sweep_touch", True)),
            "sweep_ticks_experimental": int(entry.get("sweep_ticks_experimental", 0)),
            "order_expire_bars": int(entry.get("order_expire_bars", 36)),
            "exit_profile": (spec.get("exit_meta") or {}).get("profile", "structural_rr"),
            "reward_risk": str((spec.get("exit_meta") or {}).get("reward_risk", "2")),
            "dataset_version": (spec.get("data_context") or {}).get("dataset_version"),
        }

    def run(self) -> tuple[list[BergTnbSetup], list[Order]]:
        if not self.bars:
            return [], []
        suppress = set()
        rollover_events = (self.spec.get("data_context") or {}).get("rollover_events")
        suppress = _rollover_suppress(self.bars, self.tick, rollover_events)

        bars_4h = aggregate_bars(self.bars, "4h") if len(self.bars) >= 48 else []
        f4 = FractalConfig(self.cfg["fractal_4h_left"], self.cfg["fractal_4h_right"])
        f5 = FractalConfig(self.cfg["fractal_5m_left"], self.cfg["fractal_5m_right"])
        bias_series = build_4h_bias_series(bars_4h, f4) if bars_4h else []
        fractals_5m = confirmed_fractals(self.bars, f5)
        profile = get_profile(self.cfg["session_profile"])

        setups: list[BergTnbSetup] = []
        orders: list[Order] = []
        setup = BergTnbSetup(str(uuid.uuid4()), [])
        state = BergTnbState.WAITING_FOR_4H_BIAS
        liquidity_level: Decimal | None = None
        session_rec: SessionLevelRecord | None = None
        bias_dir: str | None = None
        last_bias: Bias4hRecord | None = None
        fakeout: FakeoutFibRecord | None = None
        fakeout_done = False
        bos_done = False
        reversal_idx: int | None = None
        post_bos_high: Decimal | None = None
        post_bos_low: Decimal | None = None
        session_low_track: Decimal | None = None
        session_high_track: Decimal | None = None
        pending_order: Order | None = None
        sweep_idx: int | None = None
        current_session_lo: Decimal | None = None
        current_session_hi: Decimal | None = None
        post_bos_extreme_start: int | None = None

        for i, b in enumerate(self.bars):
            if i in suppress:
                continue

            bias_snap = bias_for_5m_bar(bars_4h, bias_series, b.ts) if bars_4h else None
            new_dir = bias_snap.direction if bias_snap else None
            if new_dir != bias_dir:
                if state not in (BergTnbState.WAITING_FOR_4H_BIAS, BergTnbState.COMPLETED):
                    _log(
                        setup,
                        ts=b.ts,
                        frm=state,
                        to=BergTnbState.INVALIDATED_OR_EXPIRED,
                        bar_index=i,
                        reason="4H bias changed",
                        evidence={"new_bias": new_dir},
                        cfg=self.cfg,
                    )
                    setups.append(setup)
                    setup = BergTnbSetup(str(uuid.uuid4()), [])
                    state = BergTnbState.WAITING_FOR_4H_BIAS
                    liquidity_level = session_rec = None
                    fakeout = None
                    fakeout_done = bos_done = False
                    reversal_idx = None
                    pending_order = None

            bias_dir = new_dir
            if bias_dir is None:
                if state != BergTnbState.WAITING_FOR_4H_BIAS:
                    state = BergTnbState.WAITING_FOR_4H_BIAS
                continue

            if bias_snap and bias_snap.record.direction:
                last_bias = bias_snap.record
                setup.bias = last_bias

            if state == BergTnbState.WAITING_FOR_4H_BIAS:
                _log(
                    setup,
                    ts=b.ts,
                    frm=state,
                    to=BergTnbState.WAITING_FOR_SESSION_LEVEL,
                    bar_index=i,
                    reason=f"4H bias {bias_dir}",
                    evidence={"bias": last_bias.__dict__ if last_bias else {}},
                    cfg=self.cfg,
                )
                state = BergTnbState.WAITING_FOR_SESSION_LEVEL

            if state == BergTnbState.WAITING_FOR_SESSION_LEVEL:
                done = completed_measurement_for_bar(b.ts, profile, self.cfg["setup_preset"])
                if done:
                    sid, start, end = done
                    extremes = aggregate_session_extremes(self.bars, start, end)
                    if extremes:
                        hi, lo = extremes
                        liq = lo if bias_dir == "bullish" else hi
                        session_rec = SessionLevelRecord(
                            sid,
                            start,
                            end,
                            hi,
                            lo,
                            liq,
                            bias_dir,  # type: ignore[arg-type]
                            profile.key,
                            self.cfg["setup_preset"],
                        )
                        setup.session_level = session_rec
                        liquidity_level = liq
                        current_session_lo = lo
                        current_session_hi = hi
                        _log(
                            setup,
                            ts=b.ts,
                            frm=state,
                            to=BergTnbState.WAITING_FOR_SWEEP,
                            bar_index=i,
                            reason="Previous session level locked",
                            evidence={"liquidity_level": str(liq), "session_id": sid},
                            cfg=self.cfg,
                        )
                        state = BergTnbState.WAITING_FOR_SWEEP
                continue

            if current_session_lo is not None and liquidity_level is not None and state not in (
                BergTnbState.WAITING_FOR_4H_BIAS,
                BergTnbState.WAITING_FOR_SESSION_LEVEL,
            ):
                current_session_lo = min(current_session_lo, b.low)
                current_session_hi = max(current_session_hi or b.high, b.high)

            if state == BergTnbState.WAITING_FOR_SWEEP and liquidity_level is not None:
                swept = False
                pen = Decimal(0)
                kind = "touch"
                if bias_dir == "bullish":
                    if b.low <= liquidity_level:
                        swept = True
                        pen = liquidity_level - b.low
                else:
                    if b.high >= liquidity_level:
                        swept = True
                        pen = b.high - liquidity_level
                min_pen = self.tick * self.cfg["sweep_ticks_experimental"]
                if swept and min_pen > 0 and pen < min_pen:
                    swept = False
                if swept:
                    sweep_idx = i
                    _log(
                        setup,
                        ts=b.ts,
                        frm=state,
                        to=BergTnbState.WAITING_FOR_REVERSAL_CANDLE,
                        bar_index=i,
                        reason="Liquidity sweep/touch",
                        evidence={"penetration": str(pen)},
                        cfg=self.cfg,
                    )
                    setup.sweep = SweepRecord(
                        b.ts,
                        i,
                        pen,
                        kind,
                        {"o": str(b.open), "h": str(b.high), "l": str(b.low), "c": str(b.close)},
                    )
                    state = BergTnbState.WAITING_FOR_REVERSAL_CANDLE
                continue

            if state == BergTnbState.WAITING_FOR_REVERSAL_CANDLE:
                d = _candle_dir(b.open, b.close, self.cfg["doji_mode"])
                need = "bullish" if bias_dir == "bullish" else "bearish"
                if d == need:
                    reversal_idx = i
                    setup.reversal_bar_index = i
                    _log(
                        setup,
                        ts=b.ts,
                        frm=state,
                        to=BergTnbState.WAITING_FOR_FAKEOUT_0079,
                        bar_index=i,
                        reason="First reversal candle",
                        cfg=self.cfg,
                    )
                    state = BergTnbState.WAITING_FOR_FAKEOUT_0079
                continue

            if state == BergTnbState.WAITING_FOR_FAKEOUT_0079 and reversal_idx is not None and session_rec and sweep_idx is not None:
                anchor_hi, anchor_lo = fakeout_anchor_extremes(
                    self.bars,
                    session_high=session_rec.session_high,
                    session_low=session_rec.session_low,
                    from_index=sweep_idx,
                    to_index=i,
                )
                ratio = Decimal(self.cfg["fib_fakeout_ratio"])
                level = fib_fakeout_level(anchor_hi, anchor_lo, bias_dir, ratio)
                fakeout = FakeoutFibRecord(
                    anchor_hi,
                    anchor_lo,
                    self.bars[reversal_idx].ts,
                    self.bars[sweep_idx].ts,
                    level,
                    None,
                    None,
                )
                setup.fakeout = fakeout
                if fakeout_touched(bias_dir, level, b.low, b.high):
                    fakeout.confirmed_ts = b.ts
                    fakeout.bar_index = i
                    fakeout_done = True
                    _log(
                        setup,
                        ts=b.ts,
                        frm=state,
                        to=BergTnbState.WAITING_FOR_5M_BOS,
                        bar_index=i,
                        reason="0.079 fakeout touch",
                        evidence={"level": str(level), "anchor_hi": str(anchor_hi), "anchor_lo": str(anchor_lo)},
                        cfg=self.cfg,
                    )
                    state = BergTnbState.WAITING_FOR_5M_BOS
                continue

            if state == BergTnbState.WAITING_FOR_5M_BOS and fakeout_done and not bos_done:
                ok, fract = _bos_after_fakeout(self.bars, fractals_5m, i, bias_dir)
                if ok and fract and fakeout and fakeout.bar_index is not None and i > fakeout.bar_index:
                    ticks = int(abs(b.close - fract.level) / self.tick)
                    setup.bos = Bos5mRecord(
                        fract.level,
                        fract.confirm_index,
                        b.ts,
                        i,
                        bias_dir,  # type: ignore[arg-type]
                        ticks,
                    )
                    bos_done = True
                    post_bos_extreme_start = i
                    post_bos_high = b.high
                    post_bos_low = b.low
                    session_low_track = current_session_lo or b.low
                    session_high_track = current_session_hi or b.high
                    _log(
                        setup,
                        ts=b.ts,
                        frm=state,
                        to=BergTnbState.TRACKING_ENTRY_FIB,
                        bar_index=i,
                        reason="5m BOS after fakeout",
                        evidence={"level": str(fract.level)},
                        cfg=self.cfg,
                    )
                    state = BergTnbState.TRACKING_ENTRY_FIB
                continue

            if state == BergTnbState.TRACKING_ENTRY_FIB and bos_done and pending_order is None:
                if post_bos_extreme_start is not None:
                    post_bos_high = max(post_bos_high or b.high, b.high)
                    post_bos_low = min(post_bos_low or b.low, b.low)
                if current_session_lo is not None:
                    session_low_track = current_session_lo
                if current_session_hi is not None:
                    session_high_track = current_session_hi
                for j in range((post_bos_extreme_start or i), i + 1):
                    post_bos_high = max(post_bos_high or self.bars[j].high, self.bars[j].high)
                    post_bos_low = min(post_bos_low or self.bars[j].low, self.bars[j].low)
                ratio = Decimal(self.cfg["entry_fib_ratio"])
                if bias_dir == "bullish":
                    low_a = session_low_track or b.low
                    high_a = post_bos_high or b.high
                else:
                    low_a = post_bos_low or b.low
                    high_a = session_high_track or b.high
                limit = fib_entry_limit(low_a, high_a, bias_dir, ratio, self.tick)
                setup.entry_fib = EntryFibRecord(low_a, high_a, b.ts, b.ts, ratio, limit, [])
                structural = (
                    (session_low_track - self.tick * 2)
                    if bias_dir == "bullish"
                    else (session_high_track + self.tick * 2)
                )
                stop, target, exit_label = resolve_exit_prices(
                    self.cfg["exit_profile"],
                    direction=bias_dir,
                    entry=limit,
                    structural_stop=structural,
                    tick=self.tick,
                )
                pending_order = Order(
                    "berg_tnb_model_v1",
                    "long" if bias_dir == "bullish" else "short",
                    i,
                    limit,
                    round_tick(stop, self.tick, "down" if bias_dir == "bullish" else "up"),
                    round_tick(target, self.tick, "up" if bias_dir == "bullish" else "down"),
                    i + self.cfg["order_expire_bars"],
                    f"Berg TNB entry fib {ratio}; exit={exit_label}",
                )
                orders.append(pending_order)
                setup.order_index = i
                _log(
                    setup,
                    ts=b.ts,
                    frm=BergTnbState.TRACKING_ENTRY_FIB,
                    to=BergTnbState.LIMIT_ORDER_PENDING,
                    bar_index=i,
                    reason="Entry limit placed",
                    evidence={"limit": str(limit), "exit_profile": exit_label},
                    cfg=self.cfg,
                )
                _log(
                    setup,
                    ts=b.ts,
                    frm=BergTnbState.LIMIT_ORDER_PENDING,
                    to=BergTnbState.COMPLETED,
                    bar_index=i,
                    reason="Setup sequenced; execution delegated",
                    cfg=self.cfg,
                )
                setups.append(setup)
                setup = BergTnbSetup(str(uuid.uuid4()), [])
                state = BergTnbState.WAITING_FOR_SESSION_LEVEL if bias_dir else BergTnbState.WAITING_FOR_4H_BIAS
                liquidity_level = None
                session_rec = None
                fakeout_done = bos_done = False
                reversal_idx = None
                pending_order = None

        if setup.transitions and setup not in setups:
            setups.append(setup)
        return setups, orders