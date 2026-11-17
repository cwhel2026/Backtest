"""Small parameter grids for autonomous search."""

from copy import deepcopy
from typing import Any


def risk_variants(base: dict[str, Any], *, max_variants: int = 5) -> list[dict[str, Any]]:
    exit_spec = base.get("exit") or {}
    base_name = base.get("name", "Strategy")
    grids = [
        (exit_spec.get("stop_ticks", 16), exit_spec.get("target_ticks", 32)),
        (12, 28),
        (16, 32),
        (20, 40),
        (24, 48),
        (16, 24),
    ]
    out: list[dict[str, Any]] = []
    seen: set[tuple[int, int]] = set()
    for stop, target in grids:
        if (stop, target) in seen:
            continue
        seen.add((stop, target))
        v = deepcopy(base)
        v["exit"] = {**exit_spec, "stop_ticks": int(stop), "target_ticks": int(target), "session_end_flatten": True}
        v["name"] = f"{base_name} · {stop}/{target} ticks"
        out.append(v)
        if len(out) >= max_variants:
            break
    return out