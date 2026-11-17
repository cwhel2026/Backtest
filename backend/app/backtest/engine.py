from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

from app.backtest.bars import Bar, resample_if_needed
from app.backtest.dsl import EntrySignal, session_keys_rth, signal_at_bar, validate_spec
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
    commission_side = assumptions.commission_per_side or instrument.default_commission_per_side
    slip = assumptions.slippage_ticks_per_side
    dollar_risk = Decimal(str(spec["risk"].get("dollar_risk_per_trade", 100)))
    max_contracts = int(spec["risk"].get("max_contracts", 1))

    simulated: list[SimulatedTrade] = []
    trade_ledgers: list[dict] = []
    equity = starting_equity
    equity_curve = [{"ts": bars[0].ts.isoformat(), "equity": float(equity)}]

    i = 0
    while i < len(bars) - 2:
        sig = signal_at_bar(spec, bars, i, session_keys, tick)
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
        stop = sig.stop_price
        target = sig.target_price

        exit_px = entry_px
        exit_ts = entry_bar.ts
        exit_reason = "session_end"
        mae = Decimal(0)
        mfe = Decimal(0)

        j = i + 1
        while j < len(bars):
            b = bars[j]
            bar_mae = Decimal(0)
            bar_mfe = Decimal(0)
            if sig.direction == "long":
                bar_mfe = max(Decimal(0), (b.high - entry_px) * instrument.multiplier * qty)
                bar_mae = max(Decimal(0), (entry_px - b.low) * instrument.multiplier * qty)
                stop_hit = b.low <= stop
                target_hit = b.high >= target
            else:
                bar_mfe = max(Decimal(0), (entry_px - b.low) * instrument.multiplier * qty)
                bar_mae = max(Decimal(0), (b.high - entry_px) * instrument.multiplier * qty)
                stop_hit = b.high >= stop
                target_hit = b.low <= target

            mae = max(mae, bar_mae)
            mfe = max(mfe, bar_mfe)

            if stop_hit:
                exit_px = _apply_slippage(stop, sig.direction, "exit", tick, slip)
                exit_ts = b.ts
                exit_reason = "stop_loss"
                break
            if target_hit:
                exit_px = _apply_slippage(target, sig.direction, "exit", tick, slip)
                exit_ts = b.ts
                exit_reason = "take_profit"
                break

            if j + 1 < len(bars) and session_keys[j + 1] != session_keys[j] and spec.get("exit", {}).get(
                "session_end_flatten", True
            ):
                exit_px = _apply_slippage(b.close, sig.direction, "exit", tick, slip)
                exit_ts = b.ts
                exit_reason = "session_flatten"
                break
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
        i = j + 1

    metrics = compute_metrics(simulated, starting_equity)
    return BacktestResult(trade_ledgers, metrics, equity_curve, warnings)