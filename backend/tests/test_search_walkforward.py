from app.services.search_walkforward import (
    aggregate_fold_metrics,
    folds_pass_oos,
    split_holdout,
    walk_forward_folds,
)


class _Bar:
    def __init__(self, i: int):
        self.i = i


def test_split_holdout_is_time_ordered():
    bars = [_Bar(i) for i in range(200)]
    research, holdout = split_holdout(bars, 0.2)
    assert len(research) == 160
    assert len(holdout) == 40
    assert research[-1].i == 159
    assert holdout[0].i == 160


def test_walk_forward_folds_splits():
    bars = [_Bar(i) for i in range(300)]
    folds = walk_forward_folds(bars, 3)
    assert len(folds) >= 2
    for train, test in folds:
        assert len(train) >= 40
        assert len(test) >= 15


def test_aggregate_fold_metrics_conservative_wr():
    folds = [
        {"total_net_profit": 100, "win_rate": 0.55, "profit_factor": 1.3, "trade_count": 10},
        {"total_net_profit": 80, "win_rate": 0.40, "profit_factor": 1.2, "trade_count": 8},
    ]
    agg = aggregate_fold_metrics(folds)
    assert agg is not None
    assert agg["win_rate"] == 0.40
    assert agg["fold_count"] == 2


def test_folds_pass_requires_majority():
    ok = [{"total_net_profit": 10, "win_rate": 0.5, "profit_factor": 1.1, "trade_count": 6}] * 2
    bad = {"total_net_profit": -5, "win_rate": 0.2, "profit_factor": 0.8, "trade_count": 5}

    def chk(m):
        return float(m.get("total_net_profit") or 0) > 0

    assert folds_pass_oos(ok, min_folds=2, min_win_rate=0.38, per_fold_check=chk)
    assert not folds_pass_oos([ok[0], bad, ok[0]], min_folds=3, min_win_rate=0.38, per_fold_check=chk)