from app.services.strategy_search_space import FAMILY_BUILDERS, all_search_specs, sample_search_specs


def test_search_pool_is_large():
    assert len(all_search_specs("MES")) > 200


def test_sample_respects_budget():
    assert len(sample_search_specs("MNQ", 50, seed=1)) == 50


def test_sample_covers_new_families():
    specs = sample_search_specs("NQ", 90, seed=7)
    types = {s["entry"]["type"] for s in specs}
    assert "rsi_reversion" in types
    assert "donchian_breakout" in types
    assert "consecutive_closes" in types
    assert set(FAMILY_BUILDERS) >= {"orb", "ema", "vwap", "rsi", "donchian", "streak"}