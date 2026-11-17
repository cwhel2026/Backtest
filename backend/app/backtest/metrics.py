from dataclasses import dataclass
from decimal import Decimal
from statistics import mean, pstdev


@dataclass
class SimulatedTrade:
    direction: str
    quantity: int
    net_pnl: Decimal
    gross_pnl: Decimal
    commissions: Decimal
    slippage: Decimal
    mae: Decimal
    mfe: Decimal


def compute_metrics(trades: list[SimulatedTrade], starting_equity: Decimal = Decimal("100000")) -> dict:
    if not trades:
        return {
            "total_net_profit": 0.0,
            "gross_profit": 0.0,
            "gross_loss": 0.0,
            "profit_factor": None,
            "win_rate": None,
            "trade_count": 0,
            "expectancy_per_trade": None,
            "max_drawdown": 0.0,
            "sharpe_per_trade": None,
        }

    nets = [t.net_pnl for t in trades]
    wins = [x for x in nets if x > 0]
    losses = [x for x in nets if x <= 0]
    gross_profit = sum(wins, Decimal(0))
    gross_loss = abs(sum(losses, Decimal(0)))
    pf = float(gross_profit / gross_loss) if gross_loss > 0 else None

    equity = starting_equity
    peak = equity
    max_dd = Decimal(0)
    curve = []
    for n in nets:
        equity += n
        curve.append(float(equity))
        peak = max(peak, equity)
        dd = peak - equity
        max_dd = max(max_dd, dd)

    sharpe = None
    if len(nets) > 1:
        stdev = pstdev([float(x) for x in nets])
        if stdev > 0:
            sharpe = float(mean([float(x) for x in nets]) / stdev)

    return {
        "total_net_profit": float(sum(nets, Decimal(0))),
        "gross_profit": float(gross_profit),
        "gross_loss": float(gross_loss),
        "profit_factor": pf,
        "win_rate": len(wins) / len(nets),
        "average_win": float(mean([float(x) for x in wins])) if wins else None,
        "average_loss": float(mean([float(x) for x in losses])) if losses else None,
        "expectancy_per_trade": float(mean([float(x) for x in nets])),
        "max_drawdown": float(max_dd),
        "sharpe_per_trade": sharpe,
        "trade_count": len(trades),
        "commissions_paid": float(sum((t.commissions for t in trades), Decimal(0))),
        "slippage_total": float(sum((t.slippage for t in trades), Decimal(0))),
        "performance_category": "backtest",
    }