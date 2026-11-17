"""Signal-first combinatorial search — families sampled evenly, one risk profile."""

from __future__ import annotations

import random
from decimal import Decimal
from itertools import product
from typing import Any, Iterator

SESSION = {"allowed": ["RTH"], "timezone": "America/Chicago"}
DEFAULT_RISK = {"dollar_risk_per_trade": 75, "max_contracts": 3}

# Include tighter R:R so reverse/fade (high WR, small winners) can survive.
STOP_TARGETS = (
    (8, 12),
    (8, 16),
    (10, 20),
    (12, 18),
    (12, 24),
    (16, 24),
    (16, 32),
    (20, 30),
    (20, 40),
)


def _base(symbol: str, timeframe: str, category: str, entry: dict, name: str) -> dict[str, Any]:
    return {
        "name": name,
        "instrument_symbol": symbol.upper(),
        "timeframe": timeframe,
        "category": category,
        "session": dict(SESSION),
        "entry": entry,
        "exit": {"stop_ticks": 16, "target_ticks": 32, "session_end_flatten": True},
        "risk": dict(DEFAULT_RISK),
    }


def _with_exits(base: dict[str, Any], stop: int, target: int) -> dict[str, Any]:
    copy = {
        **base,
        "exit": {"stop_ticks": stop, "target_ticks": target, "session_end_flatten": True},
        "name": f"{base['name']} {stop}/{target}",
    }
    return copy


def _orb_specs(symbol: str, timeframe: str = "5m") -> Iterator[dict[str, Any]]:
    for minutes, side, (stop, target) in product((10, 15, 20, 30), ("both", "long", "short"), STOP_TARGETS):
        base = _base(
            symbol,
            timeframe,
            "opening_range_breakout",
            {"type": "opening_range_breakout", "range_minutes": minutes, "side": side},
            f"{symbol} ORB {minutes}m {side}",
        )
        yield _with_exits(base, stop, target)


def _ema_specs(symbol: str, timeframe: str = "5m") -> Iterator[dict[str, Any]]:
    pairs = ((5, 13), (8, 21), (9, 26), (12, 26), (13, 34), (20, 50))
    for (fast, slow), (stop, target) in product(pairs, STOP_TARGETS):
        if fast >= slow:
            continue
        base = _base(
            symbol,
            timeframe,
            "trend_continuation",
            {"type": "ema_crossover", "fast_period": fast, "slow_period": slow},
            f"{symbol} EMA {fast}/{slow}",
        )
        yield _with_exits(base, stop, target)


def _vwap_specs(symbol: str, timeframe: str = "5m") -> Iterator[dict[str, Any]]:
    for dev, (stop, target) in product((10, 14, 16, 20, 24, 32), STOP_TARGETS):
        base = _base(
            symbol,
            timeframe,
            "vwap_mean_reversion",
            {"type": "vwap_reversion", "deviation_ticks": dev},
            f"{symbol} VWAP rev {dev}t",
        )
        yield _with_exits(base, stop, target)


def _rsi_specs(symbol: str, timeframe: str = "5m") -> Iterator[dict[str, Any]]:
    for period, oversold, overbought, (stop, target) in product(
        (7, 14),
        (25, 30),
        (70, 75),
        STOP_TARGETS,
    ):
        if oversold >= overbought:
            continue
        base = _base(
            symbol,
            timeframe,
            "rsi_reversion",
            {
                "type": "rsi_reversion",
                "period": period,
                "oversold": oversold,
                "overbought": overbought,
            },
            f"{symbol} RSI {period} {oversold}/{overbought}",
        )
        yield _with_exits(base, stop, target)


def _donchian_specs(symbol: str, timeframe: str = "5m") -> Iterator[dict[str, Any]]:
    for lookback, (stop, target) in product((10, 16, 20, 30), STOP_TARGETS):
        base = _base(
            symbol,
            timeframe,
            "donchian_breakout",
            {"type": "donchian_breakout", "lookback": lookback},
            f"{symbol} Donchian {lookback}",
        )
        yield _with_exits(base, stop, target)


def _fvg_specs(symbol: str, timeframe: str = "5m") -> Iterator[dict[str, Any]]:
    for min_gap, max_age, side, (stop, target) in product(
        (2, 4, 6),
        (24, 36, 48),
        ("both", "long", "short"),
        STOP_TARGETS[:6],
    ):
        base = _base(
            symbol,
            timeframe,
            "fair_value_gap",
            {
                "type": "fair_value_gap",
                "min_gap_ticks": min_gap,
                "max_age_bars": max_age,
                "side": side,
            },
            f"{symbol} FVG {min_gap}t {max_age}b {side}",
        )
        yield _with_exits(base, stop, target)


def _bollinger_specs(symbol: str, timeframe: str = "5m") -> Iterator[dict[str, Any]]:
    for period, mult, (stop, target) in product((14, 20), (Decimal("1.5"), Decimal("2"), Decimal("2.5")), STOP_TARGETS[:7]):
        base = _base(
            symbol,
            timeframe,
            "bollinger_reversion",
            {"type": "bollinger_reversion", "period": period, "std_mult": float(mult)},
            f"{symbol} BB {period} {mult}",
        )
        yield _with_exits(base, stop, target)


def _liquidity_sweep_specs(symbol: str, timeframe: str = "5m") -> Iterator[dict[str, Any]]:
    for lookback, sweep, (stop, target) in product((8, 12, 16), (1, 2, 3), STOP_TARGETS[:6]):
        base = _base(
            symbol,
            timeframe,
            "liquidity_sweep",
            {"type": "liquidity_sweep", "lookback": lookback, "sweep_ticks": sweep},
            f"{symbol} liq sweep {lookback}/{sweep}t",
        )
        yield _with_exits(base, stop, target)


def _ema_pullback_specs(symbol: str, timeframe: str = "5m") -> Iterator[dict[str, Any]]:
    pairs = ((8, 21), (9, 26), (12, 26))
    for (fast, slow), (stop, target) in product(pairs, STOP_TARGETS[:8]):
        if fast >= slow:
            continue
        base = _base(
            symbol,
            timeframe,
            "ema_pullback",
            {"type": "ema_pullback", "fast_period": fast, "slow_period": slow},
            f"{symbol} EMA pull {fast}/{slow}",
        )
        yield _with_exits(base, stop, target)


def _streak_specs(symbol: str, timeframe: str = "5m") -> Iterator[dict[str, Any]]:
    for count, (stop, target) in product((3, 4, 5), STOP_TARGETS):
        base = _base(
            symbol,
            timeframe,
            "consecutive_closes",
            {"type": "consecutive_closes", "count": count},
            f"{symbol} streak {count}",
        )
        yield _with_exits(base, stop, target)


FAMILY_BUILDERS = {
    "orb": _orb_specs,
    "ema": _ema_specs,
    "ema_pullback": _ema_pullback_specs,
    "vwap": _vwap_specs,
    "rsi": _rsi_specs,
    "donchian": _donchian_specs,
    "streak": _streak_specs,
    "fvg": _fvg_specs,
    "bollinger": _bollinger_specs,
    "liquidity": _liquidity_sweep_specs,
}


def family_pools(symbol: str, timeframe: str = "5m") -> dict[str, list[dict[str, Any]]]:
    return {name: list(builder(symbol, timeframe)) for name, builder in FAMILY_BUILDERS.items()}


def all_search_specs(symbol: str, timeframe: str = "5m") -> list[dict[str, Any]]:
    specs: list[dict[str, Any]] = []
    for builder in FAMILY_BUILDERS.values():
        specs.extend(builder(symbol, timeframe))
    return specs


def sample_search_specs(symbol: str, budget: int, *, seed: int | None = None) -> list[dict[str, Any]]:
    """Draw evenly from each family so ORB stop-grid doesn't crowd out RSI/Donchian."""
    universe = all_search_specs(symbol)
    if budget >= len(universe):
        return universe
    pools = family_pools(symbol)
    rng = random.Random(seed)
    families = [name for name, pool in pools.items() if pool]
    if not families or budget <= 0:
        return []
    per = max(1, budget // len(families))
    out: list[dict[str, Any]] = []
    seen: set[str] = set()
    for name in families:
        pool = pools[name]
        take = min(per, len(pool))
        picked = rng.sample(pool, take) if take < len(pool) else list(pool)
        for spec in picked:
            key = spec["name"]
            if key not in seen:
                seen.add(key)
                out.append(spec)
            if len(out) >= budget:
                return out
    leftover = budget - len(out)
    if leftover > 0:
        rest = [s for s in all_search_specs(symbol) if s["name"] not in seen]
        extra = rng.sample(rest, min(leftover, len(rest))) if rest else []
        out.extend(extra)
    return out[:budget]


def refine_spec(spec: dict[str, Any]) -> list[dict[str, Any]]:
    """Local mutations around a near-miss candidate."""
    stop = int(spec["exit"]["stop_ticks"])
    target = int(spec["exit"]["target_ticks"])
    out: list[dict[str, Any]] = []
    for ds, dt in ((-2, 0), (0, 4), (2, 4), (-2, -4), (2, 0), (0, -4)):
        s2, t2 = max(4, stop + ds), max(6, target + dt)
        if s2 < 4 or t2 < 6:
            continue
        copy = {**spec, "exit": {**spec["exit"], "stop_ticks": s2, "target_ticks": t2}}
        copy["name"] = f"{spec['name']} refine {s2}/{t2}"
        out.append(copy)
    return out
