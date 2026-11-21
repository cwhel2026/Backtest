from unittest.mock import MagicMock, patch

from app.services.ai_arena.fingerprint import spec_fingerprint
from app.services.ai_arena.llm_providers import list_provider_catalog, build_provider


def test_spec_fingerprint_stable():
    a = {"instrument_symbol": "MNQ", "timeframe": "5m", "entry": {"type": "ema_crossover"}, "exit": {"stop_ticks": 20}}
    b = dict(a)
    assert spec_fingerprint(a) == spec_fingerprint(b)
    c = {**a, "entry": {**a["entry"], "fast_period": 8}}
    assert spec_fingerprint(a) != spec_fingerprint(c)


def test_provider_catalog_lists_eight():
    cats = list_provider_catalog()
    assert len(cats) == 8
    slugs = {c["slug"] for c in cats}
    assert "openai" in slugs and "mistral" in slugs


def test_openai_unconfigured_has_no_key():
    with patch("app.services.ai_arena.llm_providers.get_settings") as gs:
        gs.return_value.openai_api_key = ""
        p = build_provider("openai")
        assert p is not None
        assert not p.api_key_configured()


def test_cycle_skips_when_disabled():
    from app.models.ai_arena import AiResearcher
    from app.services.ai_arena.cycle import run_researcher_cycle

    r = AiResearcher(provider_slug="openai", display_name="OpenAI", enabled=False, activated_by_user=False)
    session = MagicMock()
    with patch("app.services.ai_arena.guardrails.arena_globally_allowed", return_value=True):
        out = run_researcher_cycle(session, r)
    assert out.get("skipped")