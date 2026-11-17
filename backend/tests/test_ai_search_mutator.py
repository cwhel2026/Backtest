from unittest.mock import patch

from app.services.ai_search_mutator import propose_search_specs


def test_heuristic_mutations_validate(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "")
    monkeypatch.setenv("AI_RESEARCH_ENABLED", "false")
    from app.core.config import get_settings

    get_settings.cache_clear()
    _, specs = propose_search_specs("MNQ", "no trials yet", max_specs=5, seed=1)
    assert 1 <= len(specs) <= 5
    for s in specs:
        assert s["instrument_symbol"] == "MNQ"
        assert s["exit"]["session_end_flatten"] is True


@patch("app.services.ai_search_mutator.get_settings")
def test_openai_fallback_to_heuristic(mock_settings):
    mock_settings.return_value.ai_configured = True
    mock_settings.return_value.openai_api_key = "sk-test"
    mock_settings.return_value.openai_model = "gpt-4o-mini"
    with patch("httpx.Client.post", side_effect=OSError("offline")):
        rationale, specs = propose_search_specs("MES", "near-miss list", max_specs=3, seed=2)
    assert "heuristic" in rationale.lower() or specs
    assert len(specs) <= 3