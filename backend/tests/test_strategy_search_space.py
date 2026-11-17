from app.services.strategy_search_space import all_search_specs, sample_search_specs


def test_search_pool_is_large():
    assert len(all_search_specs("MES")) > 200


def test_sample_respects_budget():
    assert len(sample_search_specs("MNQ", 50, seed=1)) == 50