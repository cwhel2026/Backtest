from app.services.prop_screen import is_profitable_backtest, prop_readiness_score


def test_rejects_losing_strategy():
    assert not is_profitable_backtest(
        {"total_net_profit": -500, "profit_factor": 0.3, "trade_count": 50, "max_drawdown": 2000}
    )


def test_accepts_winner():
    m = {"total_net_profit": 1200, "profit_factor": 1.4, "trade_count": 30, "max_drawdown": 800, "win_rate": 0.55}
    assert is_profitable_backtest(m)
    assert prop_readiness_score(m) >= 45


def test_rejects_swing_style_low_win_rate():
    """High PF with ~20% WR is not intraday prop-ready."""
    m = {
        "total_net_profit": 2500,
        "profit_factor": 2.1,
        "trade_count": 40,
        "max_drawdown": 900,
        "win_rate": 0.19,
    }
    assert not is_profitable_backtest(m)
    assert prop_readiness_score(m) == 0


def test_win_rate_dominates_readiness_score():
    strong_wr = {
        "total_net_profit": 900,
        "profit_factor": 1.25,
        "trade_count": 25,
        "max_drawdown": 700,
        "win_rate": 0.58,
    }
    weak_wr = {**strong_wr, "profit_factor": 1.8, "total_net_profit": 1800, "win_rate": 0.43}
    assert prop_readiness_score(strong_wr) > prop_readiness_score(weak_wr)