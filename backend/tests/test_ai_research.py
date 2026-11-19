from app.backtest.dsl import validate_spec
from app.services.ai_research import generate_hypothesis_and_spec


def test_heuristic_vwap_prompt():
    rationale, spec = generate_hypothesis_and_spec("MNQ", "5m", "vwap mean reversion fade")
    assert spec["entry"]["type"] == "vwap_reversion"
    assert validate_spec(spec) == []


def test_heuristic_ema_default():
    _, spec = generate_hypothesis_and_spec("MES", "5m", "momentum trend")
    assert spec["entry"]["type"] == "ema_crossover"
    assert validate_spec(spec) == []