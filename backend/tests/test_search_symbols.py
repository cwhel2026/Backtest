from app.services.autonomous_cycle import resolve_search_symbols


def test_nasdaq_always_included(monkeypatch):
    monkeypatch.setenv("SEARCH_SYMBOLS", "MES,ES")
    # Clear settings cache if needed
    from app.core.config import get_settings

    get_settings.cache_clear()
    syms = resolve_search_symbols()
    assert "MNQ" in syms
    assert "NQ" in syms
    get_settings.cache_clear()