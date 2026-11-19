from app.services.research_grade import (
    GRADE_CANDIDATE,
    GRADE_KEEPER,
    GRADE_MISS,
    GRADE_PROBE,
    bootstrap_mean_ci,
    effective_grade,
    research_grade,
)
from app.services.search_walkforward import split_holdout


FOUR_TRADE_ORB = {
    "total_net_profit": 2137,
    "profit_factor": 91.93,
    "trade_count": 4,
    "max_drawdown": 24,
    "win_rate": 0.75,
    "expectancy_per_trade": 534,
}


def test_yahoo_1m_four_trade_orb_is_a_probe_not_a_keeper():
    grade = research_grade(
        FOUR_TRADE_ORB,
        timeframe="1m",
        data_source="yahoo_finance",
        sample_days=6.5,
    )
    assert grade == GRADE_PROBE
    assert effective_grade(FOUR_TRADE_ORB, timeframe="1m", data_source="yahoo") == GRADE_PROBE


def test_legacy_four_trade_without_grade_infers_probe():
    assert effective_grade(FOUR_TRADE_ORB, timeframe="1m") == GRADE_PROBE


def test_losing_run_is_miss():
    assert research_grade({"total_net_profit": -10, "trade_count": 20, "profit_factor": 0.8}) == GRADE_MISS


def test_5m_green_with_ci_and_holdout_is_keeper():
    metrics = {
        "total_net_profit": 1800,
        "profit_factor": 1.45,
        "trade_count": 28,
        "max_drawdown": 700,
        "win_rate": 0.54,
        "expectancy_ci_low": 12.0,
        "expectancy_ci_high": 90.0,
        "holdout_net": 220,
    }
    oos = {"total_net_profit": 400, "profit_factor": 1.3, "trade_count": 8, "win_rate": 0.5}
    holdout = {"total_net_profit": 220, "trade_count": 6}
    assert research_grade(metrics, oos=oos, holdout=holdout, timeframe="5m") == GRADE_KEEPER


def test_ci_including_zero_is_candidate():
    metrics = {
        "total_net_profit": 900,
        "profit_factor": 1.25,
        "trade_count": 22,
        "max_drawdown": 600,
        "win_rate": 0.5,
        "expectancy_ci_low": -8.0,
        "expectancy_ci_high": 40.0,
    }
    oos = {"total_net_profit": 120, "trade_count": 6, "profit_factor": 1.2, "win_rate": 0.5}
    assert research_grade(metrics, oos=oos, timeframe="5m") == GRADE_CANDIDATE


def test_holdout_loss_is_candidate():
    metrics = {
        "total_net_profit": 1400,
        "profit_factor": 1.4,
        "trade_count": 20,
        "max_drawdown": 500,
        "win_rate": 0.52,
        "expectancy_ci_low": 5.0,
        "expectancy_ci_high": 80.0,
    }
    oos = {"total_net_profit": 200, "trade_count": 5, "profit_factor": 1.2, "win_rate": 0.5}
    holdout = {"total_net_profit": -180, "trade_count": 4}
    assert research_grade(metrics, oos=oos, holdout=holdout, timeframe="5m") == GRADE_CANDIDATE


def test_paid_1m_long_window_can_be_keeper():
    metrics = {
        "total_net_profit": 2100,
        "profit_factor": 1.5,
        "trade_count": 18,
        "max_drawdown": 400,
        "win_rate": 0.55,
        "expectancy_ci_low": 15.0,
        "expectancy_ci_high": 95.0,
        "holdout_net": 150,
    }
    oos = {"total_net_profit": 300, "trade_count": 5, "profit_factor": 1.3, "win_rate": 0.6}
    holdout = {"total_net_profit": 150, "trade_count": 4}
    assert (
        research_grade(
            metrics,
            oos=oos,
            holdout=holdout,
            timeframe="1m",
            data_source="finzdata",
            sample_days=30,
        )
        == GRADE_KEEPER
    )


def test_bootstrap_ci_all_winners_excludes_zero():
    lo, hi = bootstrap_mean_ci([10.0, 12.0, 9.0, 11.0, 8.0], seed=1)
    assert lo is not None and hi is not None
    assert lo > 0
    assert hi >= lo


def test_bootstrap_ci_needs_four_trades():
    assert bootstrap_mean_ci([1.0, 2.0, 3.0]) == (None, None)


def test_split_holdout_keeps_last_fifth():
    bars = list(range(100))
    research, holdout = split_holdout(bars, 0.2)
    assert research == list(range(80))
    assert holdout == list(range(80, 100))
    assert split_holdout(list(range(20)), 0.2) == (list(range(20)), [])
