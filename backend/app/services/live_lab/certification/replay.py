"""Deterministic replay certification — triple replay + restart checkpoints."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal

from app.backtest.bars import Bar
from app.backtest.video_strategies import Order, VideoConfig
from app.models.enums import AssetClass
from app.models.instrument import Instrument
from app.services.live_lab.incremental_executor import ForwardExecutorState, IncrementalVideoForwardEngine


@dataclass
class ReplayCertResult:
    passed: bool
    fingerprint: str
    runs: int = 3
    restart_checks: list[dict] = field(default_factory=list)
    divergences: list[str] = field(default_factory=list)


def _mes() -> Instrument:
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


def _synthetic_bars(n: int = 12) -> list[Bar]:
    from datetime import timedelta

    t0 = datetime(2024, 1, 2, 14, 30, tzinfo=UTC)
    rows = []
    for i in range(n):
        px = Decimal(5000 + i)
        rows.append(Bar(t0 + timedelta(minutes=5 * i), px, px + 2, px - 2, px + Decimal("0.5"), 100))
    rows[4] = Bar(rows[4].ts, Decimal(5004), Decimal(5005), Decimal(4998), Decimal(4999), 120)
    return rows


def _run_forward_path(bars: list[Bar], restart_at: int | None = None) -> dict:
    cfg = VideoConfig.from_instrument(_mes(), {})
    order = Order(
        "cert",
        "long",
        2,
        Decimal(4999),
        Decimal(4994),
        Decimal(5010),
        8,
        "cert_limit",
        setup_id="cert-setup-1",
    )
    ledger: list[dict] = []
    state = ForwardExecutorState()
    eng = IncrementalVideoForwardEngine(state, cfg, _mes())
    eng.submit_order(order, bars)

    for i in range(3, len(bars)):
        if restart_at is not None and i == restart_at:
            state = ForwardExecutorState(
                version=state.version,
                last_bar_ts=state.last_bar_ts,
                bars_count=state.bars_count,
                busy_until=state.busy_until,
                pending=list(state.pending),
                open_position=state.open_position,
                placed_setup_keys=list(state.placed_setup_keys),
            )
            eng = IncrementalVideoForwardEngine(state, cfg, _mes())
        result = eng.on_bar(bars[: i + 1], i)
        for ev in result.events:
            ledger.append({"i": i, **ev})
        if result.trade_closed:
            ledger.append({"i": i, "type": "trade_closed", "trade": _serialize_trade(result.trade_closed)})

    return {
        "ledger": ledger,
        "final_state": eng.state,
        "equity_pnl": str(sum(Decimal(str(x["trade"]["net_pnl"])) for x in ledger if x.get("type") == "trade_closed")),
    }


def _serialize_trade(t: dict) -> dict:
    out = {}
    for k, v in t.items():
        if hasattr(v, "isoformat"):
            out[k] = v.isoformat()
        elif isinstance(v, Decimal):
            out[k] = str(v)
        else:
            out[k] = v
    return out


def _fingerprint(payload: dict) -> str:
    raw = json.dumps(payload, sort_keys=True, default=str)
    return hashlib.sha256(raw.encode()).hexdigest()


def certify_replay_triple(*, restart_points: list[int] | None = None) -> ReplayCertResult:
    restart_points = restart_points or [5, 7]
    bars = _synthetic_bars()
    baselines = [_run_forward_path(bars) for _ in range(3)]
    fp0 = _fingerprint(baselines[0])
    divergences: list[str] = []
    for idx, run in enumerate(baselines[1:], start=2):
        fp = _fingerprint(run)
        if fp != fp0:
            divergences.append(f"run_{idx}_fingerprint_mismatch")

    restart_checks = []
    for pt in restart_points:
        if pt >= len(bars) - 1:
            continue
        restarted = _run_forward_path(bars, restart_at=pt)
        restart_fp = _fingerprint(restarted)
        restart_checks.append({"restart_at_bar": pt, "fingerprint": restart_fp, "match_baseline": restart_fp == fp0})
        if restart_fp != fp0:
            divergences.append(f"restart_at_{pt}_mismatch")

    return ReplayCertResult(
        passed=len(divergences) == 0,
        fingerprint=fp0,
        restart_checks=restart_checks,
        divergences=divergences,
    )