"""Build reproducible simulation provenance payloads for debugger replay."""

from __future__ import annotations

import hashlib
import json
from typing import Any

from app.backtest import ENGINE_VERSION


def specification_hash(spec: dict) -> str:
    payload = json.dumps(spec, sort_keys=True, default=str)
    return hashlib.sha256(payload.encode()).hexdigest()[:16]


def build_simulation_provenance(
    *,
    spec: dict,
    instrument_symbol: str,
    dataset_version: str | None,
    dataset_checksum: str | None,
    timeframe: str,
    bar_count: int,
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    base = {
        "engine_version": ENGINE_VERSION,
        "strategy_config_hash": specification_hash(spec),
        "instrument": instrument_symbol,
        "timeframe": timeframe,
        "dataset_version": dataset_version,
        "dataset_checksum": dataset_checksum,
        "bar_count": bar_count,
        "entry_type": (spec.get("entry") or {}).get("type"),
    }
    if extra:
        base.update(extra)
    return base