from decimal import Decimal

from app.backtest.metrics import SimulatedTrade, compute_metrics


def _trade(net: str) -> SimulatedTrade:
    n = Decimal(net)
    return SimulatedTrade(
        direction="long",
        quantity=1,
        net_pnl=n,
        gross_pnl=n,
        commissions=Decimal("0"),
        slippage=Decimal("0"),
        mae=Decimal("0"),
        mfe=Decimal("0"),
    )


def test_sharpe_none_when_all_trade_pnls_identical():
    trades = [_trade("10"), _trade("10"), _trade("10")]
    metrics = compute_metrics(trades)
    assert metrics["sharpe_per_trade"] is None
    assert metrics["trade_count"] == 3


def test_sharpe_computed_when_pnls_vary():
    trades = [_trade("10"), _trade("-5"), _trade("15")]
    metrics = compute_metrics(trades)
    assert metrics["sharpe_per_trade"] is not None