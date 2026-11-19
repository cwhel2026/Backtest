"""Controlled research matrix — baseline vs labelled experiments."""

from __future__ import annotations

from dataclasses import dataclass
from itertools import product
from typing import Any

BASELINE_ENTRY = {
    "session_profile": "pdf_indices",
    "setup_preset": "new_york_setup",
    "fib_fakeout_ratio": "0.079",
    "entry_fib_ratio": "0.618",
    "allow_exact_sweep_touch": True,
    "sweep_ticks_experimental": 0,
}

EXPERIMENTAL_ENTRY_RATIOS = ["0.500", "0.550", "0.595", "0.618"]
SESSION_PROFILES = ["pdf_indices", "pdf_forex", "cme_futures_research"]
EXIT_PROFILES = ["structural_rr", "fixed_ticks", "swing", "time_exit"]


@dataclass
class MatrixCell:
    label: str
    kind: str
    specification_patch: dict[str, Any]


def research_matrix(baseline_spec: dict) -> list[MatrixCell]:
    """Enumerate labelled variants — caller must run each chronologically with walk-forward splits."""
    cells: list[MatrixCell] = [MatrixCell("baseline", "baseline", {})]
    entry = dict(baseline_spec.get("entry") or {})
    for ratio in EXPERIMENTAL_ENTRY_RATIOS:
        if ratio != entry.get("entry_fib_ratio", "0.618"):
            cells.append(
                MatrixCell(
                    f"entry_fib_{ratio}",
                    "experimental",
                    {"entry": {**entry, "entry_fib_ratio": ratio}},
                )
            )
    for profile in SESSION_PROFILES:
        if profile != entry.get("session_profile", "pdf_indices"):
            cells.append(
                MatrixCell(
                    f"session_{profile}",
                    "experimental",
                    {"entry": {**entry, "session_profile": profile}},
                )
            )
    for ex in EXIT_PROFILES:
        cells.append(
            MatrixCell(
                f"exit_{ex}",
                "experimental",
                {"exit_meta": {"profile": ex, "reward_risk": "2"}},
            )
        )
    cells.append(
        MatrixCell(
            "sweep_penetration_1tick",
            "experimental",
            {"entry": {**entry, "sweep_ticks_experimental": 1}},
        )
    )
    return cells


def walk_forward_splits(bar_count: int, train_pct: float = 0.6, val_pct: float = 0.2) -> dict[str, tuple[int, int]]:
    """Index ranges for chronological train/val/OOS (no shuffle)."""
    if bar_count < 100:
        return {"train": (0, bar_count)}
    train_end = int(bar_count * train_pct)
    val_end = int(bar_count * (train_pct + val_pct))
    return {
        "train": (0, train_end),
        "validate": (train_end, val_end),
        "oos": (val_end, bar_count),
    }