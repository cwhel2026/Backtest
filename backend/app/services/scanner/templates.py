"""Default scanner strategy templates — detection only, same engines as Live Lab."""

from __future__ import annotations

MARKET_SCANNER_TEMPLATES: list[dict] = [
    {
        "strategy_key": "berg_tnb",
        "strategy_name": "Berg TNB",
        "strategy_version": "berg_tnb_model_v1",
        "spec": {
            "entry": {"type": "berg_tnb_model_v1"},
            "risk": {"dollar_risk_per_trade": 75, "max_contracts": 1},
            "exit_meta": {"profile": "structural_rr"},
        },
    },
    {
        "strategy_key": "liquidity_sweep",
        "strategy_name": "Liquidity Sweep",
        "strategy_version": "video_liquidity_sweep_incremental_v1",
        "spec": {
            "entry": {"type": "video_liquidity_sweep"},
            "risk": {"dollar_risk_per_trade": 75, "max_contracts": 1},
        },
    },
    {
        "strategy_key": "anchor_bos",
        "strategy_name": "Anchor Break of Structure",
        "strategy_version": "video_anchor_bos_incremental_v1",
        "spec": {
            "entry": {"type": "video_anchor_bos"},
            "risk": {"dollar_risk_per_trade": 75, "max_contracts": 1},
        },
    },
]