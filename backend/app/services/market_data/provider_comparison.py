"""Provider comparison for MNQ/MES/MGC — costs cited from public Databento unit pricing (Dec 2024 PDF)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

# GLBX.MDP3 OHLCV-1m historical: $70/GB (metered) per Databento unit pricing PDF 2024-12-11.
DATABENTO_GLBX_OHLCV_1M_USD_PER_GB = 70.0

PHASE2_MICROS = ("MNQ", "MES", "MGC")

PROVIDER_COMPARISON: list[dict[str, Any]] = [
    {
        "id": "databento",
        "name": "Databento GLBX.MDP3",
        "tier": "primary",
        "genuine_for_research": True,
        "mnq_mes_mgc": True,
        "ohlcv_1m": True,
        "ohlcv_5m": "Derived from 1m in-app",
        "contract_id": "ROOT.c.0 continuous unadjusted (default)",
        "rollover": "Documented roll events; unadjusted prices",
        "licensing": "Exchange-licensed via Databento; pay-per-GB + venue fees",
        "typical_cost_gbp_month_note": "Use in-app estimate (metadata.get_cost). List rate ≈ $70/GB OHLCV-1m; "
        "14d MNQ often sub-£5–£15 but verify with your API key.",
        "budget_fit_0_50_gbp": True,
        "ingest_path": "Historical Data → Databento → estimate → approve → queue",
    },
    {
        "id": "csv",
        "name": "CSV import",
        "tier": "primary",
        "genuine_for_research": True,
        "mnq_mes_mgc": True,
        "ohlcv_1m": True,
        "ohlcv_5m": True,
        "contract_id": "User-defined",
        "rollover": "User must supply or accept WARNING",
        "licensing": "You must own rights to the file",
        "typical_cost_gbp_month_note": "£0 if you already purchased data elsewhere",
        "budget_fit_0_50_gbp": True,
        "ingest_path": "Historical Data → import CSV",
    },
    {
        "id": "yahoo",
        "name": "Yahoo Finance (continuous)",
        "tier": "fallback",
        "genuine_for_research": False,
        "mnq_mes_mgc": True,
        "ohlcv_1m": "~7 days only",
        "ohlcv_5m": "Limited history",
        "contract_id": "Ticker alias (MES=F)",
        "rollover": "Adjusted continuous — not outright tradable prices",
        "licensing": "Delayed/unlicensed — smoke tests only",
        "typical_cost_gbp_month_note": "£0",
        "budget_fit_0_50_gbp": True,
        "ingest_path": "Not recommended for Berg/video research",
    },
    {
        "id": "finzdata",
        "name": "FinzData",
        "tier": "fallback",
        "genuine_for_research": False,
        "mnq_mes_mgc": True,
        "ohlcv_1m": "Paid plan",
        "ohlcv_5m": True,
        "contract_id": "API-specific",
        "rollover": "Check vendor docs",
        "licensing": "Vendor subscription",
        "typical_cost_gbp_month_note": "Variable — confirm plan",
        "budget_fit_0_50_gbp": "Maybe on low tiers",
        "ingest_path": "Worker finzdata provider",
    },
    {
        "id": "ibkr",
        "name": "IBKR Gateway",
        "tier": "experimental",
        "genuine_for_research": True,
        "mnq_mes_mgc": True,
        "ohlcv_1m": "Chunked historical",
        "ohlcv_5m": True,
        "contract_id": "Outright conids",
        "rollover": "Manual per contract",
        "licensing": "IB account + market data subs",
        "typical_cost_gbp_month_note": "IB market data fees apply",
        "budget_fit_0_50_gbp": "Often yes for paper",
        "ingest_path": "Experimental worker path",
    },
]


def comparison_catalog() -> dict[str, Any]:
    return {
        "updated": datetime.now(UTC).isoformat(),
        "budget_gbp_default": 50,
        "recommended_primary": "databento",
        "micro_contracts": list(PHASE2_MICROS),
        "databento_list_rate_usd_per_gb_ohlcv_1m": DATABENTO_GLBX_OHLCV_1M_USD_PER_GB,
        "databento_pricing_source_url": "https://databento.com/pricing",
        "providers": PROVIDER_COMPARISON,
        "workflow": [
            "Prefer 1m Databento download → store parquet + checksum",
            "Select 5m dataset version derived from same 1m fingerprint",
            "Berg TNB uses 5m bars; 4H bias aggregated without lookahead",
        ],
        "live_cost_estimate_available": False,
        "live_cost_note": "Set DATABENTO_API_KEY on server; use POST /market-data/ingest/estimate-range",
    }


def quote_micro_bundle_days(days: int, *, gbp_usd: float | None = None) -> dict[str, Any]:
    """Optional live quotes when Databento key configured; otherwise returns estimate unavailable."""
    from app.core.config import get_settings

    settings = get_settings()
    out: dict[str, Any] = {"days": days, "symbols": {}, "available": False}
    if not settings.databento_configured:
        out["note"] = "DATABENTO_API_KEY not set — use dashboard after configuring Railway secret."
        return out
    from app.services.market_data.databento_client import quote_download_cost

    end = datetime.now(UTC)
    start = end - timedelta(days=days)
    out["available"] = True
    for sym in PHASE2_MICROS:
        q = quote_download_cost(sym, start, end, gbp_usd_rate=gbp_usd or settings.gbp_usd_rate)
        out["symbols"][sym] = q.to_dict()
    return out