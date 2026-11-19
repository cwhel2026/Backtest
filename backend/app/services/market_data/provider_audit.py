"""Provider classification for Historical Data Engine 3.0 (reference constants)."""

PROVIDER_TIERS = {
    "databento": {
        "tier": "primary",
        "serious_intraday": True,
        "note": "Licensed GLBX.MDP3 ohlcv-1m; official cost API; parquet library.",
    },
    "finzdata": {
        "tier": "fallback",
        "serious_intraday": True,
        "note": "Paid intraday when plan allows; daily-only on free tier.",
    },
    "yahoo": {
        "tier": "fallback",
        "serious_intraday": False,
        "note": "Free delayed; 1m ~7d cap — not suitable for serious intraday research.",
    },
    "ibkr": {
        "tier": "experimental",
        "serious_intraday": True,
        "note": "Gateway historical; requires co-located network; single-chunk limits.",
    },
    "csv": {
        "tier": "primary",
        "serious_intraday": True,
        "note": "User-supplied; validated like other sources.",
    },
}