from pathlib import Path

from app.services.live_lab.market_data.ibkr_fixture import IbkrFixtureAdapter


def test_ibkr_fixture_loads_and_dedupes():
    path = Path(__file__).parent / "fixtures" / "ibkr_sample_ticks.jsonl"
    ad = IbkrFixtureAdapter(["MNQ", "MES"], path=path)
    ad.connect()
    batch1 = ad.poll_events(limit=10)
    batch2 = ad.poll_events(limit=10)
    assert len(batch1) == 3
    assert batch2 == []
    desc = ad.describe()
    assert desc["latency_mode"] == "delayed"
    assert "recorded" in desc["note"].lower()