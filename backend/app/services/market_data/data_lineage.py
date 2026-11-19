"""Dataset lineage — distinguish licensed history from free/synthetic sources.

Backtests labelled 'genuine historical research' must use datasets with
`genuine_for_research=True` in meta (set during validation).
"""

from __future__ import annotations

from typing import Any

DataLineage = str  # licensed_databento | user_csv | free_delayed | synthetic_test | unknown

LINEAGE_GENUINE: frozenset[str] = frozenset({"licensed_databento", "user_csv"})

LINEAGE_LABELS: dict[str, str] = {
    "licensed_databento": "Licensed CME Globex (Databento) — unadjusted continuous",
    "user_csv": "User-supplied CSV (validated, not exchange-licensed unless you own rights)",
    "free_delayed": "Free/delayed feed (Yahoo/Finz free) — not for serious intraday research",
    "synthetic_test": "Synthetic/test — never use for profitability research",
    "unknown": "Unknown source — verify before research",
}


def lineage_from_provider(provider_slug: str, meta: dict[str, Any] | None = None) -> DataLineage:
    slug = (provider_slug or "").lower()
    meta = meta or {}
    if meta.get("synthetic") is True or meta.get("source") == "synthetic_test":
        return "synthetic_test"
    if slug == "databento" or meta.get("source") == "databento_historical":
        return "licensed_databento"
    if slug in ("csv", "import", "user"):
        return "user_csv"
    if slug == "yahoo":
        return "free_delayed"
    if slug == "finzdata":
        if meta.get("finzdata_tier") == "paid_intraday":
            return "licensed_databento"  # treat paid vendor as research-grade when flagged
        return "free_delayed"
    if slug == "ibkr":
        return "user_csv"  # user gateway — research OK with disclosure
    return "unknown"


def apply_lineage_meta(meta: dict[str, Any], *, provider_slug: str) -> dict[str, Any]:
    out = dict(meta or {})
    lineage = lineage_from_provider(provider_slug, out)
    out["data_lineage"] = lineage
    out["data_lineage_label"] = LINEAGE_LABELS.get(lineage, LINEAGE_LABELS["unknown"])
    out["genuine_for_research"] = lineage in LINEAGE_GENUINE
    out["tradable_prices"] = lineage == "licensed_databento" or (
        lineage == "user_csv" and out.get("user_asserts_licensed") is True
    )
    if lineage == "licensed_databento":
        out.setdefault(
            "continuous_contract_note",
            "Unadjusted front continuous (.c.0) — prices reflect roll jumps; not single outright.",
        )
    if lineage == "free_delayed":
        out.setdefault(
            "research_warning",
            "Free/delayed source: do not report results as exchange-grade historical research.",
        )
    if lineage == "synthetic_test":
        out.setdefault("research_warning", "Synthetic data — tests only.")
    return out


def assert_genuine_for_backtest(meta: dict[str, Any] | None) -> None:
    meta = meta or {}
    if meta.get("synthetic") is True or meta.get("data_lineage") == "synthetic_test":
        raise ValueError(
            "Dataset is synthetic/test-only. Ingest licensed Databento history or a validated CSV for genuine research."
        )
    lineage = meta.get("data_lineage")
    if lineage and lineage not in LINEAGE_GENUINE:
        raise ValueError(
            f"Dataset lineage '{lineage}' is not approved for genuine historical research "
            f"({meta.get('data_lineage_label', '')}). Use Databento (paid) or user CSV with documented rights."
        )
    if meta.get("genuine_for_research") is False:
        raise ValueError(meta.get("research_warning") or "Dataset not marked genuine_for_research.")