"""Detect duplicate / near-duplicate strategy specifications."""

from __future__ import annotations

import hashlib
import json
from typing import Any


def spec_fingerprint(spec: dict[str, Any]) -> str:
    """Stable hash over normalized entry/exit/timeframe/symbol (ignores names)."""
    entry = spec.get("entry") or {}
    exit_s = spec.get("exit") or {}
    core = {
        "instrument_symbol": str(spec.get("instrument_symbol") or "").upper(),
        "timeframe": str(spec.get("timeframe") or "5m"),
        "entry_type": entry.get("type"),
        "entry": {k: entry.get(k) for k in sorted(entry) if k != "name"},
        "exit": {k: exit_s.get(k) for k in sorted(exit_s)},
        "filters": spec.get("filters"),
    }
    raw = json.dumps(core, sort_keys=True, default=str)
    return hashlib.sha256(raw.encode()).hexdigest()[:32]