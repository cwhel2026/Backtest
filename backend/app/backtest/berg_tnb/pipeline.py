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
from app.backtest.berg_tnb.sessions import (
    aggregate_session_extremes,
    completed_measurement_for_bar,
    entry_fib_trading_active,
    get_profile,
)
from app.backtest.berg_tnb.fsm_state import BergTnbFsmState
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
from app.backtest.berg_tnb.events import emit
from app.backtest.berg_tnb.fractals import ConfirmedFractal
from app.backtest.decision_events import DecisionEvent, DecisionEventType, RejectedSetup
from app.backtest.video_strategies import Order, OrderAmendment, effective_order_prices, round_tick


def effective_order_prices_for_bar(order: Order, bar_index: int):
    return effective_order_prices(order, bar_index)


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
            "entry_fib_mode": entry.get("entry_fib_mode", "single_snapshot"),
            "exit_profile": (spec.get("exit_meta") or {}).get("profile", "structural_rr"),
            "reward_risk": str((spec.get("exit_meta") or {}).get("reward_risk", "2")),
            "dataset_version": (spec.get("data_context") or {}).get("dataset_version"),
        }

    def run(
        self,
        *,
        through_bar: int | None = None,
    ) -> tuple[list[BergTnbSetup], list[Order], list[DecisionEvent], list[RejectedSetup]]:
        events: list[DecisionEvent] = []
        rejections: list[RejectedSetup] = []
        self._forward_snapshots: dict[int, dict] = {}
        self._fsm_export: BergTnbFsmState | None = None
        if not self.bars:
            return [], [], events, rejections
        restored: BergTnbFsmState | None = None
        if self.spec.get("forward_test") and self.spec.get("_fsm_state"):
            try:
                restored = BergTnbFsmState.from_dict(self.spec["_fsm_state"])
            except ValueError:
                restored = None
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
        def _setup_id(bar_index: int, tag: str = "main") -> str:
            if self.spec.get("forward_test"):
                return f"berg-{bar_index}-{tag}"
            return str(uuid.uuid4())

        setup = BergTnbSetup(_setup_id(0, "main"), [])
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
        order_tracking_start: int | None = None

        if restored:
            setup = BergTnbSetup(restored.setup_id or _setup_id(max(restored.last_processed_bar, 0), "main"), [])
            state = restored.state
            liquidity_level = restored.liquidity_level
            bias_dir = restored.bias_dir
            fakeout_done = restored.fakeout_done
            bos_done = restored.bos_done
            reversal_idx = restored.reversal_idx
            sweep_idx = restored.sweep_idx
            post_bos_high = restored.post_bos_high
            post_bos_low = restored.post_bos_low
            session_low_track = restored.session_low_track
            session_high_track = restored.session_high_track
            pending_order = restored.pending_order
            current_session_lo = restored.current_session_lo
            current_session_hi = restored.current_session_hi
            post_bos_extreme_start = restored.post_bos_extreme_start
            order_tracking_start = restored.order_tracking_start
            extra = restored.extra or {}
            if extra.get("session_rec"):
                sr = extra["session_rec"]
                session_rec = SessionLevelRecord(
                    sr["session_id"],
                    datetime.fromisoformat(sr["measurement_start"]),
                    datetime.fromisoformat(sr["measurement_end"]),
                    Decimal(sr["session_high"]),
                    Decimal(sr["session_low"]),
                    Decimal(sr["liquidity_level"]),
                    sr["bias"],
                    sr["profile"],
                    sr["setup_preset"],
                )
            if extra.get("fakeout"):
                fo = extra["fakeout"]
                fakeout = FakeoutFibRecord(
                    Decimal(fo["anchor_high"]),
                    Decimal(fo["anchor_low"]),
                    datetime.fromisoformat(fo["anchor_high_ts"]),
                    datetime.fromisoformat(fo["anchor_low_ts"]),
                    Decimal(fo["level_0079"]),
                    datetime.fromisoformat(fo["confirmed_ts"]) if fo.get("confirmed_ts") else None,
                    fo.get("bar_index"),
                )
        loop_start = (restored.last_processed_bar + 1) if restored else 0

        def _reset_active_setup() -> None:
            nonlocal setup, state, liquidity_level, session_rec, fakeout, fakeout_done, bos_done
            nonlocal reversal_idx, pending_order, sweep_idx, post_bos_high, post_bos_low
            nonlocal session_low_track, session_high_track, post_bos_extreme_start, order_tracking_start
            setup_holder = BergTnbSetup(_setup_id(i, "reset"), [])
            setup = setup_holder
            state = BergTnbState.WAITING_FOR_SESSION_LEVEL if bias_dir else BergTnbState.WAITING_FOR_4H_BIAS
            liquidity_level = None
            session_rec = None
            fakeout = None
            fakeout_done = bos_done = False
            reversal_idx = None
            pending_order = None
            sweep_idx = None
            post_bos_high = post_bos_low = None
            session_low_track = session_high_track = None
            post_bos_extreme_start = None
            order_tracking_start = None

        def _complete_setup(reason: str) -> None:
            nonlocal setup, state
            _log(
                setup,
                ts=b.ts,
                frm=state,
                to=BergTnbState.COMPLETED,
                bar_index=i,
                reason=reason,
                cfg=self.cfg,
            )
            setups.append(setup)
            _reset_active_setup()

        def _process_entry_fib() -> None:
            nonlocal pending_order, state, post_bos_high, post_bos_low, session_low_track, session_high_track
            nonlocal order_tracking_start
            if not bos_done or bias_dir is None:
                return
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
            structural = (
                (session_low_track - self.tick * 2)
                if bias_dir == "bullish" and session_low_track is not None
                else (session_high_track + self.tick * 2)
                if bias_dir == "bearish" and session_high_track is not None
                else None
            )
            if structural is None:
                return
            stop, target, exit_label = resolve_exit_prices(
                self.cfg["exit_profile"],
                direction=bias_dir,
                entry=limit,
                structural_stop=structural,
                tick=self.tick,
            )
            mode = self.cfg.get("entry_fib_mode", "single_snapshot")
            trading_ok = entry_fib_trading_active(b.ts, profile)
            expired = order_tracking_start is not None and i >= order_tracking_start + self.cfg["order_expire_bars"]
            if not trading_ok or expired:
                if pending_order is not None and mode == "dynamic_pdf_experimental":
                    emit(
                        events,
                        ts=b.ts,
                        bar_index=i,
                        event_type=DecisionEventType.ORDER_EXPIRED,
                        setup_id=setup.setup_id,
                        direction=bias_dir,
                        explanation="Entry fib tracking cutoff (session or bar expiry)",
                        rule_id="berg.entry_fib.cutoff",
                        source="interpretation",
                        levels={"limit": str(pending_order.limit)},
                    )
                elif pending_order is None:
                    rejections.append(
                        RejectedSetup(
                            ts=b.ts,
                            bar_index=i,
                            strategy=self.cfg["strategy_id"],
                            setup_id=setup.setup_id,
                            reason_code="ENTRY_FIB_CUTOFF_NO_ORDER",
                            explanation="Entry fib window ended before a limit could be placed",
                            rule_id="berg.entry_fib.cutoff",
                            source="interpretation",
                        )
                    )
                _complete_setup("Entry fib tracking complete")
                return

            if pending_order is None:
                pending_order = Order(
                    self.cfg["strategy_id"],
                    "long" if bias_dir == "bullish" else "short",
                    i,
                    limit,
                    round_tick(stop, self.tick, "down" if bias_dir == "bullish" else "up"),
                    round_tick(target, self.tick, "up" if bias_dir == "bullish" else "down"),
                    i + self.cfg["order_expire_bars"],
                    f"Berg TNB entry fib {ratio}; exit={exit_label}",
                    setup_id=setup.setup_id,
                )
                orders.append(pending_order)
                setup.order_index = i
                order_tracking_start = i
                setup.entry_fib = EntryFibRecord(
                    low_a,
                    high_a,
                    b.ts,
                    b.ts,
                    ratio,
                    limit,
                    [],
                )
                fib_source = (
                    "experimental" if mode == "dynamic_pdf_experimental" else "pdf_confirmed"
                )
                emit(
                    events,
                    ts=b.ts,
                    bar_index=i,
                    event_type=DecisionEventType.FIB_ANCHOR_CREATED,
                    setup_id=setup.setup_id,
                    direction=bias_dir,
                    explanation="Entry Fibonacci anchors locked for limit",
                    rule_id="berg.entry_fib.anchor",
                    source=fib_source,
                    levels={"low": str(low_a), "high": str(high_a), "limit": str(limit)},
                )
                emit(
                    events,
                    ts=b.ts,
                    bar_index=i,
                    event_type=DecisionEventType.ORDER_SUBMITTED,
                    setup_id=setup.setup_id,
                    direction=bias_dir,
                    explanation="Limit order submitted at entry fib",
                    rule_id="berg.entry_fib.order",
                    source=fib_source,
                    levels={"limit": str(limit), "stop": str(stop), "target": str(target)},
                )
                _log(
                    setup,
                    ts=b.ts,
                    frm=BergTnbState.TRACKING_ENTRY_FIB,
                    to=BergTnbState.LIMIT_ORDER_PENDING,
                    bar_index=i,
                    reason="Entry limit placed",
                    evidence={"limit": str(limit), "exit_profile": exit_label, "mode": mode},
                    cfg=self.cfg,
                )
                state = (
                    BergTnbState.LIMIT_ORDER_PENDING
                    if mode == "dynamic_pdf_experimental"
                    else BergTnbState.TRACKING_ENTRY_FIB
                )
                if mode == "single_snapshot":
                    _complete_setup("Setup sequenced; execution delegated")
                return

            eff_lim, _, _ = effective_order_prices_for_bar(pending_order, i)
            if limit != eff_lim and mode == "dynamic_pdf_experimental":
                before = {"limit": str(eff_lim)}
                stp = round_tick(stop, self.tick, "down" if bias_dir == "bullish" else "up")
                tgt = round_tick(target, self.tick, "up" if bias_dir == "bullish" else "down")
                pending_order.amendments.append(
                    OrderAmendment(i, limit, stp, tgt, b.ts)
                )
                if setup.entry_fib:
                    setup.entry_fib.limit_price = limit
                    setup.entry_fib.anchor_low = low_a
                    setup.entry_fib.anchor_high = high_a
                    setup.entry_fib.updates.append(
                        {"ts": b.ts.isoformat(), "bar_index": i, "limit": str(limit), "low": str(low_a), "high": str(high_a)}
                    )
                emit(
                    events,
                    ts=b.ts,
                    bar_index=i,
                    event_type=DecisionEventType.FIB_ANCHOR_UPDATED,
                    setup_id=setup.setup_id,
                    direction=bias_dir,
                    explanation="Post-BOS extreme advanced; Fibonacci entry repriced",
                    rule_id="berg.entry_fib.dynamic",
                    source="experimental",
                    levels={"limit": str(limit), "low": str(low_a), "high": str(high_a)},
                    before_state=before,
                    after_state={"limit": str(limit)},
                )
                emit(
                    events,
                    ts=b.ts,
                    bar_index=i,
                    event_type=DecisionEventType.ORDER_AMENDED,
                    setup_id=setup.setup_id,
                    direction=bias_dir,
                    explanation="Pending limit amended (experimental dynamic entry fib)",
                    rule_id="berg.entry_fib.amend",
                    source="experimental",
                    levels=before,
                    after_state={"limit": str(limit)},
                )

        def _capture_forward_state(bar_index: int) -> dict:
            return {
                "version": 1,
                "bar_index": bar_index,
                "state": state.value,
                "bias_dir": bias_dir,
                "fakeout_done": fakeout_done,
                "bos_done": bos_done,
                "reversal_idx": reversal_idx,
                "sweep_idx": sweep_idx,
                "setup_id": setup.setup_id,
                "pending_order": (
                    {
                        "signal_index": pending_order.signal_index,
                        "limit": str(pending_order.limit),
                        "direction": pending_order.direction,
                    }
                    if pending_order
                    else None
                ),
                "order_tracking_start": order_tracking_start,
            }

        def _export_fsm(i: int) -> BergTnbFsmState:
            extra: dict[str, Any] = {}
            if session_rec:
                extra["session_rec"] = {
                    "session_id": session_rec.session_id,
                    "measurement_start": session_rec.measurement_start.isoformat(),
                    "measurement_end": session_rec.measurement_end.isoformat(),
                    "session_high": str(session_rec.session_high),
                    "session_low": str(session_rec.session_low),
                    "liquidity_level": str(session_rec.liquidity_level),
                    "bias": session_rec.bias,
                    "profile": session_rec.profile,
                    "setup_preset": session_rec.setup_preset,
                }
            if fakeout:
                extra["fakeout"] = {
                    "anchor_high": str(fakeout.anchor_high),
                    "anchor_low": str(fakeout.anchor_low),
                    "anchor_high_ts": fakeout.anchor_high_ts.isoformat(),
                    "anchor_low_ts": fakeout.anchor_low_ts.isoformat(),
                    "level_0079": str(fakeout.level_0079),
                    "confirmed_ts": fakeout.confirmed_ts.isoformat() if fakeout.confirmed_ts else None,
                    "bar_index": fakeout.bar_index,
                }
            return BergTnbFsmState(
                last_processed_bar=i,
                setup_id=setup.setup_id,
                state=state,
                liquidity_level=liquidity_level,
                bias_dir=bias_dir,
                fakeout_done=fakeout_done,
                bos_done=bos_done,
                reversal_idx=reversal_idx,
                sweep_idx=sweep_idx,
                post_bos_high=post_bos_high,
                post_bos_low=post_bos_low,
                session_low_track=session_low_track,
                session_high_track=session_high_track,
                pending_order=pending_order,
                current_session_lo=current_session_lo,
                current_session_hi=current_session_hi,
                post_bos_extreme_start=post_bos_extreme_start,
                order_tracking_start=order_tracking_start,
                extra=extra,
            )

        end_i = through_bar if through_bar is not None else len(self.bars) - 1
        for i, b in enumerate(self.bars):
            if i < loop_start:
                continue
            if i > end_i:
                break
            if i in suppress:
                continue
            if i > 0 and self.spec.get("forward_test"):
                self._forward_snapshots[i - 1] = _capture_forward_state(i - 1)

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
                    setup = BergTnbSetup(_setup_id(i, "bias_reset"), [])
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

            if state in (BergTnbState.TRACKING_ENTRY_FIB, BergTnbState.LIMIT_ORDER_PENDING) and bos_done:
                _process_entry_fib()
                continue

            if self.spec.get("forward_test"):
                self._fsm_export = _export_fsm(i)

        if self.spec.get("forward_test") and self.bars:
            cap_i = min(end_i, len(self.bars) - 1)
            self._forward_snapshots[cap_i] = _capture_forward_state(cap_i)
            if self._fsm_export is None:
                self._fsm_export = _export_fsm(cap_i)

        if setup.transitions and setup not in setups:
            setups.append(setup)
        transition_events = {
            (BergTnbState.WAITING_FOR_4H_BIAS, BergTnbState.WAITING_FOR_SESSION_LEVEL): DecisionEventType.BIAS_CONFIRMED,
            (BergTnbState.WAITING_FOR_SESSION_LEVEL, BergTnbState.WAITING_FOR_SWEEP): DecisionEventType.SESSION_LEVEL_FINALIZED,
            (BergTnbState.WAITING_FOR_SWEEP, BergTnbState.WAITING_FOR_REVERSAL_CANDLE): DecisionEventType.LIQUIDITY_SWEEP_DETECTED,
            (BergTnbState.WAITING_FOR_REVERSAL_CANDLE, BergTnbState.WAITING_FOR_FAKEOUT_0079): DecisionEventType.REVERSAL_CONFIRMED,
            (BergTnbState.WAITING_FOR_FAKEOUT_0079, BergTnbState.WAITING_FOR_5M_BOS): DecisionEventType.FAKEOUT_CONFIRMED,
            (BergTnbState.WAITING_FOR_5M_BOS, BergTnbState.TRACKING_ENTRY_FIB): DecisionEventType.BOS_CONFIRMED,
        }
        for s in setups:
            for tr in s.transitions:
                et = transition_events.get((tr.from_state, tr.to_state))
                if not et:
                    continue
                emit(
                    events,
                    ts=tr.ts,
                    bar_index=tr.bar_index,
                    event_type=et,
                    setup_id=s.setup_id,
                    direction=(s.bias.direction if s.bias else None),
                    explanation=tr.reason,
                    rule_id=f"berg.{tr.to_state.value.lower()}",
                    source="pdf_confirmed",
                    levels=tr.evidence,
                )
        return setups, orders, events, rejections