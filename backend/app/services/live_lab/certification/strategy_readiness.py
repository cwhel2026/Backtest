"""Strategy engine readiness matrix for certification dashboard."""

from __future__ import annotations

from app.backtest.video_incremental import incremental_matches_batch_anchor, incremental_matches_batch_sweep


def strategy_readiness_matrix() -> dict:
    from datetime import UTC, datetime, timedelta
    from decimal import Decimal

    from app.backtest.bars import Bar
    from app.backtest.video_strategies import VideoConfig
    from app.models.enums import AssetClass
    from app.models.instrument import Instrument

    inst = Instrument(
        symbol="MES",
        name="MES",
        asset_class=AssetClass.EQUITY_INDEX,
        tick_size=Decimal("0.25"),
        tick_value=Decimal("1.25"),
        multiplier=Decimal("5"),
        trading_hours={},
        default_commission_per_side=Decimal("0.62"),
    )
    t0 = datetime(2024, 1, 2, 14, 30, tzinfo=UTC)
    bars = [
        Bar(t0 + timedelta(minutes=5 * i), Decimal(5000 + i), Decimal(5002 + i), Decimal(4998 + i), Decimal(5000 + i), 50)
        for i in range(50)
    ]
    cfg = VideoConfig.from_instrument(inst, {})

    sweep_parity = incremental_matches_batch_sweep(bars, cfg, ["s"] * len(bars))
    anchor_parity = incremental_matches_batch_anchor(bars, cfg)

    return {
        "berg_tnb": {
            "incremental_fsm": True,
            "persistent_state": True,
            "no_lookahead_htf": True,
            "replay_parity": "partial",
            "restart_recovery": True,
            "paper_certified": False,
            "note": "Forward step uses loop_start+FSM restore; verify on licensed feed",
        },
        "video_liquidity_sweep": {
            "incremental_fsm": True,
            "persistent_state": True,
            "no_lookahead": True,
            "batch_parity": sweep_parity,
            "restart_recovery": True,
            "paper_certified": sweep_parity,
        },
        "video_anchor_bos": {
            "incremental_fsm": True,
            "persistent_state": True,
            "no_lookahead": True,
            "batch_parity": anchor_parity,
            "restart_recovery": True,
            "paper_certified": anchor_parity,
        },
        "engine_versions": {
            "berg_fsm_schema": 1,
            "berg_forward_schema": 2,
            "runner_state": 3,
            "session_sweep": "video_liquidity_sweep_incremental_v1",
            "anchor_bos": "video_anchor_bos_incremental_v1",
        },
    }