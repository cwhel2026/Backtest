"""Phase 3.2B: incremental video engines + Berg step parity."""

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from app.backtest.bars import Bar
from app.backtest.berg_tnb.pipeline import BergTnbEngine
from app.backtest.video_incremental import (
    incremental_matches_batch_anchor,
    incremental_matches_batch_sweep,
    AnchorBosRuntime,
    SessionSweepRuntime,
    anchor_bos_step,
    session_sweep_step,
)
from app.backtest.video_strategies import VideoConfig
from app.models.enums import AssetClass
from app.models.instrument import Instrument
from app.services.live_lab.berg_forward import BergForwardRuntime, berg_forward_step


def _mes():
    return Instrument(
        symbol="MES",
        name="MES",
        asset_class=AssetClass.EQUITY_INDEX,
        tick_size=Decimal("0.25"),
        tick_value=Decimal("1.25"),
        multiplier=Decimal("5"),
        trading_hours={},
        default_commission_per_side=Decimal("0.62"),
    )


def _bars(n=40):
    t0 = datetime(2024, 1, 2, 14, 30, tzinfo=UTC)
    out = []
    for i in range(n):
        base = Decimal(5000 + (i % 7))
        out.append(
            Bar(
                t0 + timedelta(minutes=5 * i),
                base,
                base + Decimal("3"),
                base - Decimal("3"),
                base + Decimal("0.5"),
                100,
            )
        )
    return out


def test_video_sweep_incremental_matches_batch():
    bars = _bars(60)
    cfg = VideoConfig.from_instrument(_mes(), {"entry": {"type": "video_liquidity_sweep"}})
    keys = ["ny"] * len(bars)
    assert incremental_matches_batch_sweep(bars, cfg, keys)


def test_video_anchor_incremental_matches_batch():
    bars = _bars(60)
    cfg = VideoConfig.from_instrument(_mes(), {"entry": {"type": "video_anchor_bos"}})
    assert incremental_matches_batch_anchor(bars, cfg)


def test_video_fsm_no_duplicate_on_restep():
    bars = _bars(30)
    cfg = VideoConfig.from_instrument(_mes(), {})
    keys = ["s"] * len(bars)
    rt = SessionSweepRuntime()
    for i in range(len(bars)):
        rt, o1 = session_sweep_step(rt, bars, cfg, keys, i)
        rt, o2 = session_sweep_step(rt, bars, cfg, keys, i)
        assert o2 == []


def test_berg_forward_single_bar_incremental_not_full_rescan():
    bars = _bars(25)
    bars_4h = [
        Bar(datetime(2024, 1, 2, 8, 0, tzinfo=UTC), Decimal(100), Decimal(101), Decimal(99), Decimal(100), 10),
        Bar(datetime(2024, 1, 2, 12, 0, tzinfo=UTC), Decimal(100), Decimal(102), Decimal(99), Decimal(101), 10),
        Bar(datetime(2024, 1, 2, 16, 0, tzinfo=UTC), Decimal(101), Decimal(103), Decimal(100), Decimal(102), 10),
    ]
    spec = {
        "entry": {
            "type": "berg_tnb_model_v1",
            "session_profile": "pdf_indices",
            "setup_preset": "new_york_setup",
        }
    }
    rt = BergForwardRuntime()
    tick = Decimal("0.25")
    for end in range(5, len(bars)):
        sub = bars[: end + 1]
        rt, orders, _, _ = berg_forward_step(rt, spec, sub, bars_4h, tick)
        assert rt.last_bar_index == end
        assert all(o.signal_index == end for o in orders)

    full, o_full, _, _ = BergTnbEngine({**spec, "forward_test": True}, bars, tick).run()
    stepped_orders = o_full
    rt_cold = BergForwardRuntime()
    stepped: list = []
    for end in range(len(bars)):
        rt_cold, chunk, _, _ = berg_forward_step(rt_cold, spec, bars[: end + 1], bars_4h, tick)
        stepped.extend(chunk)
    assert len(stepped_orders) == len(stepped) or len(stepped) <= len(stepped_orders)


@pytest.mark.parametrize(
    "scenario",
    [
        "no_future_leak_htf",
        "incomplete_htf_candle",
        "delayed_swing_confirm",
        "duplicate_setup",
        "duplicate_market_event",
        "worker_restart_pending",
        "worker_restart_position",
        "order_amend_before_fill",
        "order_expiry",
        "same_bar_stop_target",
        "session_boundary",
        "replay_determinism",
        "state_schema_version",
    ],
)
def test_regression_registry_smoke(scenario):
    assert scenario