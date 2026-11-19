"""Serializable Berg TNB forward FSM state."""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any

from app.backtest.berg_tnb.types import BergTnbSetup, BergTnbState, EntryFibRecord, FakeoutFibRecord
from app.backtest.video_strategies import Order, OrderAmendment


FSM_SCHEMA_VERSION = 1


def _dec(v: Decimal | None) -> str | None:
    return str(v) if v is not None else None


def _dec_opt(s: str | None) -> Decimal | None:
    return Decimal(s) if s is not None else None


def _serialize_order(o: Order | None) -> dict | None:
    if o is None:
        return None
    return {
        "strategy": o.strategy,
        "direction": o.direction,
        "signal_index": o.signal_index,
        "limit": str(o.limit),
        "stop": str(o.stop),
        "target": str(o.target),
        "expire_index": o.expire_index,
        "reason": o.reason,
        "setup_id": o.setup_id,
        "amendments": [
            {"bar_index": a.bar_index, "limit": str(a.limit), "stop": str(a.stop), "target": str(a.target), "ts": a.ts.isoformat()}
            for a in o.amendments
        ],
    }


def _deserialize_order(raw: dict | None) -> Order | None:
    if not raw:
        return None
    from datetime import datetime

    amds = []
    for a in raw.get("amendments") or []:
        amds.append(
            OrderAmendment(
                int(a["bar_index"]),
                Decimal(a["limit"]),
                Decimal(a["stop"]),
                Decimal(a["target"]),
                datetime.fromisoformat(a["ts"]),
            )
        )
    return Order(
        raw["strategy"],
        raw["direction"],
        int(raw["signal_index"]),
        Decimal(raw["limit"]),
        Decimal(raw["stop"]),
        Decimal(raw["target"]),
        int(raw["expire_index"]),
        raw.get("reason", ""),
        setup_id=raw.get("setup_id"),
        amendments=amds,
    )


@dataclass
class BergTnbFsmState:
    version: int = FSM_SCHEMA_VERSION
    last_processed_bar: int = -1
    setup_id: str = ""
    state: BergTnbState = BergTnbState.WAITING_FOR_4H_BIAS
    liquidity_level: Decimal | None = None
    bias_dir: str | None = None
    fakeout_done: bool = False
    bos_done: bool = False
    reversal_idx: int | None = None
    sweep_idx: int | None = None
    post_bos_high: Decimal | None = None
    post_bos_low: Decimal | None = None
    session_low_track: Decimal | None = None
    session_high_track: Decimal | None = None
    pending_order: Order | None = None
    current_session_lo: Decimal | None = None
    current_session_hi: Decimal | None = None
    post_bos_extreme_start: int | None = None
    order_tracking_start: int | None = None
    emitted_order_keys: list[str] = field(default_factory=list)
    extra: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "version": self.version,
            "last_processed_bar": self.last_processed_bar,
            "setup_id": self.setup_id,
            "state": self.state.value,
            "liquidity_level": _dec(self.liquidity_level),
            "bias_dir": self.bias_dir,
            "fakeout_done": self.fakeout_done,
            "bos_done": self.bos_done,
            "reversal_idx": self.reversal_idx,
            "sweep_idx": self.sweep_idx,
            "post_bos_high": _dec(self.post_bos_high),
            "post_bos_low": _dec(self.post_bos_low),
            "session_low_track": _dec(self.session_low_track),
            "session_high_track": _dec(self.session_high_track),
            "pending_order": _serialize_order(self.pending_order),
            "current_session_lo": _dec(self.current_session_lo),
            "current_session_hi": _dec(self.current_session_hi),
            "post_bos_extreme_start": self.post_bos_extreme_start,
            "order_tracking_start": self.order_tracking_start,
            "emitted_order_keys": list(self.emitted_order_keys),
            "extra": dict(self.extra),
        }

    @classmethod
    def from_dict(cls, raw: dict | None) -> BergTnbFsmState:
        if not raw:
            return cls()
        if int(raw.get("version", 0)) != FSM_SCHEMA_VERSION:
            raise ValueError(f"Unsupported Berg FSM version {raw.get('version')}")
        return cls(
            version=FSM_SCHEMA_VERSION,
            last_processed_bar=int(raw.get("last_processed_bar", -1)),
            setup_id=str(raw.get("setup_id") or ""),
            state=BergTnbState(raw.get("state", BergTnbState.WAITING_FOR_4H_BIAS.value)),
            liquidity_level=_dec_opt(raw.get("liquidity_level")),
            bias_dir=raw.get("bias_dir"),
            fakeout_done=bool(raw.get("fakeout_done")),
            bos_done=bool(raw.get("bos_done")),
            reversal_idx=raw.get("reversal_idx"),
            sweep_idx=raw.get("sweep_idx"),
            post_bos_high=_dec_opt(raw.get("post_bos_high")),
            post_bos_low=_dec_opt(raw.get("post_bos_low")),
            session_low_track=_dec_opt(raw.get("session_low_track")),
            session_high_track=_dec_opt(raw.get("session_high_track")),
            pending_order=_deserialize_order(raw.get("pending_order")),
            current_session_lo=_dec_opt(raw.get("current_session_lo")),
            current_session_hi=_dec_opt(raw.get("current_session_hi")),
            post_bos_extreme_start=raw.get("post_bos_extreme_start"),
            order_tracking_start=raw.get("order_tracking_start"),
            emitted_order_keys=list(raw.get("emitted_order_keys") or []),
            extra=dict(raw.get("extra") or {}),
        )