from uuid import uuid4
from unittest.mock import MagicMock

from app.models.enums import DatasetValidationStatus
from app.models.market_data import DataProvider, HistoricalDataset
from app.services.market_data.data_lineage import apply_lineage_meta
from app.services.market_data.dataset_research import backfill_dataset_lineage, research_eligibility


def test_missing_lineage_not_ok():
    ds = HistoricalDataset(
        id=uuid4(),
        provider_id=uuid4(),
        instrument_id=uuid4(),
        timeframe="5m",
        validation_status=DatasetValidationStatus.VALIDATED,
        meta={"source": "legacy_import"},
    )
    assert research_eligibility(ds).ok is False


def test_yahoo_backfill_exploratory_only():
    prov = DataProvider(id=uuid4(), slug="yahoo", display_name="yahoo", config_hint="")
    ds = HistoricalDataset(
        id=uuid4(),
        provider_id=prov.id,
        instrument_id=uuid4(),
        timeframe="5m",
        validation_status=DatasetValidationStatus.VALIDATED,
        meta={},
    )
    session = MagicMock()
    session.get.return_value = prov
    backfill_dataset_lineage(session, ds)
    elig = research_eligibility(ds)
    assert elig.ok is True
    assert elig.genuine_persist is False
    assert elig.lineage == "free_delayed"


def test_databento_genuine_persist():
    meta = apply_lineage_meta({"source": "databento_historical"}, provider_slug="databento")
    ds = HistoricalDataset(
        id=uuid4(),
        provider_id=uuid4(),
        instrument_id=uuid4(),
        timeframe="5m",
        validation_status=DatasetValidationStatus.VALIDATED,
        meta=meta,
    )
    elig = research_eligibility(ds)
    assert elig.ok is True
    assert elig.genuine_persist is True