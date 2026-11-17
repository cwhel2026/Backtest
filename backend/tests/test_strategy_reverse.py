from app.services.strategy_reverse import (
    implied_reversed_win_rate,
    is_anti_edge,
    reverse_passes_oos,
    reverse_spec,
)


def test_eight_percent_win_rate_implies_ninety_two():
    assert abs(implied_reversed_win_rate(0.08) - 0.92) < 1e-9
    assert is_anti_edge({"win_rate": 0.08, "trade_count": 25, "total_net_profit": -400, "profit_factor": 0.4})


def test_healthy_winner_is_not_anti_edge():
    assert not is_anti_edge(
        {"win_rate": 0.55, "trade_count": 30, "total_net_profit": 900, "profit_factor": 1.4}
    )


def test_losing_low_wr_is_anti_edge():
    assert is_anti_edge(
        {"win_rate": 0.32, "trade_count": 20, "total_net_profit": -250, "profit_factor": 0.7}
    )


def test_reverse_spec_inverts_and_swaps_r_multiple():
    spec = {
        "name": "MES ORB 15m long 16/32",
        "category": "opening_range_breakout",
        "entry": {"type": "opening_range_breakout", "range_minutes": 15, "side": "long"},
        "exit": {"stop_ticks": 16, "target_ticks": 32, "session_end_flatten": True},
    }
    rev = reverse_spec(spec, original_metrics={"win_rate": 0.08})
    assert rev is not None
    assert rev["entry"]["invert"] is True
    assert rev["exit"]["stop_ticks"] == 32
    assert rev["exit"]["target_ticks"] == 16
    assert rev["name"].startswith("REV ")
    assert abs(rev["implied_win_rate"] - 0.92) < 1e-9
    assert reverse_spec(rev) is None


def test_reverse_oos_requires_actual_inversion():
    orig_wr = 0.08
    good = {"total_net_profit": 200, "profit_factor": 1.3, "trade_count": 10, "win_rate": 0.8}
    still_bad = {"total_net_profit": 50, "profit_factor": 1.1, "trade_count": 10, "win_rate": 0.07}
    assert reverse_passes_oos(good, orig_wr)
    assert not reverse_passes_oos(still_bad, orig_wr)
