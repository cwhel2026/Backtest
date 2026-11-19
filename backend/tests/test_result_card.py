from datetime import UTC, datetime

from app.services.result_card import build_test_meta, data_feed, risk_profile, sample_window


def test_data_feed_labels_yahoo_1m_as_probe():
    feed = data_feed(provider_slug="yahoo", provider_name="Yahoo Finance (free)", timeframe="1m", sample_days=6.5)
    assert feed["probe_feed"] is True
    assert "probe" in feed["summary"].lower()


def test_sample_window_summarizes_1m_week():
    start = datetime(2026, 11, 12, tzinfo=UTC)
    end = datetime(2026, 11, 18, 12, tzinfo=UTC)
    sample = sample_window(coverage_start=start, coverage_end=end, row_count=4200, timeframe="1m")
    assert sample["days"] == 6.5
    assert "1m" in sample["summary"]
    assert "4,200 bars" in sample["summary"]


def test_risk_profile_mes_tick_stop():
    spec = {
        "exit": {"stop_ticks": 16, "target_ticks": 24, "stop_atr": 1.0, "target_atr": 1.5},
        "risk": {"dollar_risk_per_trade": 75, "max_contracts": 1},
    }
    metrics = {"max_drawdown": 24, "average_loss": -24, "trade_count": 4}
    risk = risk_profile(spec, metrics, tick_value=1.25)
    assert risk["stop_usd"] == 20.0
    assert risk["target_usd"] == 30.0
    assert risk["reward_risk"] == 1.5
    assert "Stop 1 ATR" in risk["summary"]
    assert "$75 risk" in risk["summary"]
    assert "max DD $24" in risk["summary"]
    assert "0.02% of $100,000" in risk["summary"]


def test_test_meta_includes_oos_and_tested_at():
    tested = datetime(2026, 11, 18, 8, 40, tzinfo=UTC)
    meta = build_test_meta(
        tested_at=tested,
        params={
            "origin": "near_miss",
            "oos_metrics": {"trade_count": 2, "win_rate": 0.5, "total_net_profit": 400},
            "train_metrics": {"trade_count": 3},
        },
        metrics={"trade_count": 4},
    )
    assert meta["tested_at"] == tested.isoformat()
    assert meta["oos_trades"] == 2
    assert "OOS 2 trades, 50% WR" in meta["summary"]
    assert "full sample 4 trades" in meta["summary"]
    assert "research-window" in meta["method"]
