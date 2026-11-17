from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

from app.backtest.bars import Bar, resample_if_needed
from app.backtest.dsl import build_signal_context, session_keys_rth, signal_at_bar, validate_spec
from app.backtest.exits import (
    ManagedPosition,
    check_intrabar_exit,
    manage_at_bar_close,
    resolve_stop_target,
    time_stop_hit,
)
from app.backtest.metrics import SimulatedTrade, compute_metrics
from app.models.instrument import Instrument
from app.services.futures_math import contracts_for_risk


@dataclass
class BacktestAssumptions:
    slippage_ticks_per_side: int = 1
    commission_per_side: Decimal | None = None


@dataclass
class BacktestResult:
    trades: list[dict]
    metrics: dict
    equity_curve: list[dict]
    warnings: list[str]


def _apply_slippage(price: Decimal, direction: str, side: str, tick: Decimal, ticks: int) -> Decimal:
    adj = tick * Decimal(ticks)
    if side == "entry":
        if direction == "long":
            return price + adj
        return price - adj
    if direction == "long":
        return price - adj
    return price + adj


def _pnl_points(entry: Decimal, exit_px: Decimal, direction: str, qty: int, multiplier: Decimal) -> Decimal:
    diff = exit_px - entry if direction == "long" else entry - exit_px
    return diff * multiplier * Decimal(qty)


def run_backtest(
    spec: dict,
    bars: list[Bar],
    instrument: Instrument,
    dataset_timeframe: str,
    assumptions: BacktestAssumptions,
    starting_equity: Decimal = Decimal("100000"),
) -> BacktestResult:
    errors = validate_spec(spec)
    if errors:
        raise ValueError("; ".join(errors))

    warnings: list[str] = []
    warnings.append(
        "Signals on bar close; entries at next bar open. Intrabar stop/target: stop checked before target."
    )

    strategy_tf = spec.get("timeframe", dataset_timeframe)
    bars = resample_if_needed(bars, dataset_timeframe, strategy_tf)
    if len(bars) < 30:
        warnings.append("Fewer than 30 bars after resample — statistics may be unreliable.")

    session_keys = session_keys_rth(bars)
    tick = instrument.tick_size
    signal_ctx = build_signal_context(spec, bars, session_keys, instrument_tick=tick)
    commission_side = assumptions.commission_per_side or instrument.default_commission_per_side
    slip = assumptions.slippage_ticks_per_side
    dollar_risk = Decimal(str(spec["risk"].get("dollar_risk_per_trade", 100)))
    max_contracts = int(spec["risk"].get("max_contracts", 1))

    simulated: list[SimulatedTrade] = []
    trade_ledgers: list[dict] = []
    equity = starting_equity
    equity_curve = [{"ts": bars[0].ts.isoformat(), "equity": float(equity)}]

    trades_by_session: dict[str, int] = {}
    max_trades_day = int((spec.get("filters") or {}).get("max_trades_per_day") or 0)

    i = 0
    while i < len(bars) - 2:
        if max_trades_day and trades_by_session.get(session_keys[i], 0) >= max_trades_day:
            i += 1
            continue
        sig = signal_at_bar(spec, bars, i, session_keys, tick, signal_ctx)
        if not sig:
            i += 1
            continue

        entry_bar = bars[i + 1]
        raw_entry = entry_bar.open
        qty = contracts_for_risk(raw_entry, sig.stop_price, dollar_risk, instrument)
        qty = min(max(qty, 1 if qty > 0 else 0), max_contracts)
        if qty < 1:
            i += 1
            continue

        entry_px = _apply_slippage(raw_entry, sig.direction, "entry", tick, slip)
        atr_now = signal_ctx.atr[i] if signal_ctx.atr else None
        stop, target = resolve_stop_target(
            spec,
            direction=sig.direction,
            entry_px=entry_px,
            tick=tick,
            atr=atr_now,
            fallback_stop=sig.stop_price,
            fallback_target=sig.target_price,
        )
        position = ManagedPosition(
            direction=sig.direction,
            entry=entry_px,
            stop=stop,
            target=target,
            bars_held=0,
            initial_risk=abs(entry_px - stop),
        )

        exit_px = entry_px
        exit_ts = entry_bar.ts
        exit_reason = "session_end"
        mae = Decimal(0)
        mfe = Decimal(0)

        j = i + 1
        while j < len(bars):
            b = bars[j]
            if sig.direction == "long":
                bar_mfe = max(Decimal(0), (b.high - entry_px) * instrument.multiplier * qty)
                bar_mae = max(Decimal(0), (entry_px - b.low) * instrument.multiplier * qty)
            else:
                bar_mfe = max(Decimal(0), (entry_px - b.low) * instrument.multiplier * qty)
                bar_mae = max(Decimal(0), (b.high - entry_px) * instrument.multiplier * qty)
            mae = max(mae, bar_mae)
            mfe = max(mfe, bar_mfe)

            hit_px, hit_reason = check_intrabar_exit(sig.direction, position.stop, position.target, b)
            if hit_px is not None and hit_reason is not None:
                exit_px = _apply_slippage(hit_px, sig.direction, "exit", tick, slip)
                exit_ts = b.ts
                exit_reason = hit_reason
                stop, target = position.stop, position.target
                break

            if j + 1 < len(bars) and session_keys[j + 1] != session_keys[j] and spec.get("exit", {}).get(
                "session_end_flatten", True
            ):
                exit_px = _apply_slippage(b.close, sig.direction, "exit", tick, slip)
                exit_ts = b.ts
                exit_reason = "session_flatten"
                stop, target = position.stop, position.target
                break

            atr_j = signal_ctx.atr[j] if signal_ctx.atr else None
            position = manage_at_bar_close(position, b, spec, tick, atr_j)
            if time_stop_hit(position, spec):
                exit_px = _apply_slippage(b.close, sig.direction, "exit", tick, slip)
                exit_ts = b.ts
                exit_reason = "time_stop"
                stop, target = position.stop, position.target
                break
            stop, target = position.stop, position.target
            j += 1

        gross = _pnl_points(entry_px, exit_px, sig.direction, qty, instrument.multiplier)
        slip_cost = (
            tick * Decimal(slip) * instrument.multiplier * Decimal(qty) * Decimal(2)
        )  # approximate $ slippage
        commissions = commission_side * Decimal(2) * Decimal(qty)
        net = gross - commissions - slip_cost

        simulated.append(
            SimulatedTrade(
                sig.direction,
                qty,
                net,
                gross,
                commissions,
                slip_cost,
                mae,
                mfe,
            )
        )
        trade_ledgers.append(
            {
                "trade_number": len(trade_ledgers) + 1,
                "direction": sig.direction,
                "quantity": qty,
                "signal_ts": sig.signal_ts,
                "entry_ts": entry_bar.ts,
                "entry_price": entry_px,
                "exit_ts": exit_ts,
                "exit_price": exit_px,
                "stop_price": stop,
                "target_price": target,
                "exit_reason": exit_reason,
                "gross_pnl": gross,
                "commissions": commissions,
                "slippage": slip_cost,
                "net_pnl": net,
                "mae": mae,
                "mfe": mfe,
                "meta": {"signal_reason": sig.reason},
            }
        )
        equity += net
        equity_curve.append({"ts": exit_ts.isoformat(), "equity": float(equity)})
        trades_by_session[session_keys[i]] = trades_by_session.get(session_keys[i], 0) + 1
        i = j + 1

    metrics = compute_metrics(simulated, starting_equity)
    return BacktestResult(trade_ledgers, metrics, equity_curve, warnings)