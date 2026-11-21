from unittest.mock import MagicMock, patch

from app.services.ai_arena.guardrails import arena_globally_allowed, get_or_create_settings


def test_emergency_stop_blocks_arena():
    session = MagicMock()
    settings = MagicMock()
    settings.emergency_stop = True
    settings.global_daily_budget_usd = 100
    settings.global_monthly_budget_usd = 1000
    with patch("app.services.ai_arena.guardrails.get_or_create_settings", return_value=settings):
        with patch("app.services.ai_arena.guardrails.global_spend_usd", return_value=0):
            assert arena_globally_allowed(session) is False
        settings.emergency_stop = False
        with patch("app.services.ai_arena.guardrails.global_spend_usd", return_value=0):
            assert arena_globally_allowed(session) is True