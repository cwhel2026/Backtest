from app.services.prop_screen import is_profitable_backtest, prop_readiness_score


def test_rejects_losing_strategy():
    assert not is_profitable_backtest(
        {"total_net_profit": -500, "profit_factor": 0.3, "trade_count": 50, "max_drawdown": 2000}
    )


def test_accepts_winner():
    m = {"total_net_profit": 1200, "profit_factor": 1.4, "trade_count": 30, "max_drawdown": 800, "win_rate": 0.55}
    assert is_profitable_backtest(m)
    assert prop_readiness_score(m) >= 50