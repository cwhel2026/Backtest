"""Research eligibility — lineage backfill from provider, no fabricated licenses."""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy.orm import Session

from app.models.market_data import DataProvider, HistoricalDataset
from app.services.market_data.data_lineage import (
    LINEAGE_GENUINE,
    apply_lineage_meta,
    assert_genuine_for_backtest,
)


@dataclass(frozen=True)
class ResearchEligibility:
    ok: bool
    reason: str
    lineage: str | None
    genuine_persist: bool


def backfill_dataset_lineage(session: Session, dataset: HistoricalDataset) -> HistoricalDataset:
    """Infer lineage from provider slug when meta lacks it — does not upgrade to licensed."""
    meta = dict(dataset.meta or {})
    if meta.get("data_lineage"):
        return dataset
    provider = session.get(DataProvider, dataset.provider_id) if dataset.provider_id else None
    slug = provider.slug if provider else str(meta.get("source") or "unknown")
    merged = apply_lineage_meta(meta, provider_slug=slug)
    if merged.get("data_lineage"):
        dataset.meta = merged
        session.flush()
    return dataset


def research_eligibility(dataset: HistoricalDataset) -> ResearchEligibility:
    meta = dict(dataset.meta or {})
    lineage = meta.get("data_lineage")
    if not lineage:
        return ResearchEligibility(
            ok=False,
            reason="Dataset missing data_lineage metadata — ingest via Databento or CSV and complete validation",
            lineage=None,
            genuine_persist=False,
        )
    try:
        assert_genuine_for_backtest(meta)
        return ResearchEligibility(
            ok=True,
            reason="genuine historical research",
            lineage=str(lineage),
            genuine_persist=True,
        )
    except ValueError as exc:
        return ResearchEligibility(
            ok=True,
            reason=f"exploratory search only ({exc})",
            lineage=str(lineage),
            genuine_persist=False,
        )


def prepare_dataset_for_research(session: Session, dataset: HistoricalDataset) -> ResearchEligibility:
    dataset = backfill_dataset_lineage(session, dataset)
    return research_eligibility(dataset)