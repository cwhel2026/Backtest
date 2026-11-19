"""Incremental state machines for video liquidity sweep and anchor BOS."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from decimal import Decimal
from typing import Any

from app.backtest.bars import Bar
from app.backtest.video_strategies import Order, VideoConfig, order_from_impulse, pivots


SCHEMA_VERSION = 1


def _confirm_pivots_at_bar(bars: list[Bar], cfg: VideoConfig, i: int) -> list[tuple]:
    """Return pivot tuples newly confirmed on bar index i (confirmation lag = pivot_right)."""
    j = i - cfg.pivot_right
    if j < cfg.pivot_left or j + cfg.pivot_right != i:
        return []
    group = bars[j - cfg.pivot_left : j + cfg.pivot_right + 1]
    out: list[tuple] = []
    if bars[j].high == max(x.high for x in group) and sum(x.high == bars[j].high for x in group) == 1:
        out.append((j + cfg.pivot_right, j, "high", bars[j].high))
    if bars[j].low == min(x.low for x in group) and sum(x.low == bars[j].low for x in group) == 1:
        out.append((j + cfg.pivot_right, j, "low", bars[j].low))
    return out


@dataclass
class SessionSweepRuntime:
    version: int = SCHEMA_VERSION
    last_bar_index: int = -1
    completed: dict[str, tuple[str, str]] = field(default_factory=dict)
    active_key: str | None = None
    hi: str | None = None
    lo: str | None = None
    prev_hi: str | None = None
    prev_lo: str | None = None
    candidates: list[tuple] = field(default_factory=list)
    pivots: list[tuple] = field(default_factory=list)
    placed_setup_ids: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, raw: dict | None) -> SessionSweepRuntime:
        if not raw:
            return cls()
        return cls(
            version=int(raw.get("version", SCHEMA_VERSION)),
            last_bar_index=int(raw.get("last_bar_index", -1)),
            completed=dict(raw.get("completed") or {}),
            active_key=raw.get("active_key"),
            hi=raw.get("hi"),
            lo=raw.get("lo"),
            prev_hi=raw.get("prev_hi"),
            prev_lo=raw.get("prev_lo"),
            candidates=[tuple(c) for c in (raw.get("candidates") or [])],
            pivots=[tuple(p) for p in (raw.get("pivots") or [])],
            placed_setup_ids=list(raw.get("placed_setup_ids") or []),
        )


def session_sweep_step(
    rt: SessionSweepRuntime,
    bars: list[Bar],
    cfg: VideoConfig,
    session_keys: list[str],
    bar_index: int,
) -> tuple[SessionSweepRuntime, list[Order]]:
    if bar_index < 0 or bar_index >= len(bars):
        return rt, []
    if bar_index <= rt.last_bar_index:
        return rt, []

    b = bars[bar_index]
    key = session_keys[bar_index]
    for p in _confirm_pivots_at_bar(bars, cfg, bar_index):
        if p not in rt.pivots:
            rt.pivots.append(p)
    rt.pivots.sort(key=lambda x: x[0])

    if key != rt.active_key:
        if rt.active_key is not None and rt.hi is not None and rt.lo is not None:
            rt.completed[rt.active_key] = (rt.hi, rt.lo)
            rt.prev_hi, rt.prev_lo = rt.hi, rt.lo
        rt.active_key = key
        rt.hi = str(b.high)
        rt.lo = str(b.low)
        rt.candidates = []
    else:
        rt.hi = str(max(Decimal(rt.hi), b.high))
        rt.lo = str(min(Decimal(rt.lo), b.low))

    out: list[Order] = []
    prev = None
    if rt.prev_hi is not None and rt.prev_lo is not None:
        prev = (Decimal(rt.prev_hi), Decimal(rt.prev_lo))
    elif rt.completed:
        last_key = list(rt.completed.keys())[-1]
        ph, pl = rt.completed[last_key]
        prev = (Decimal(ph), Decimal(pl))

    if prev is not None:
        ph, pl = prev
        sweep_hi = b.high >= ph + cfg.tick * cfg.sweep_ticks and b.close < ph
        sweep_lo = b.low <= pl - cfg.tick * cfg.sweep_ticks and b.close > pl
        if sweep_hi:
            rt.candidates.append(("short", bar_index, str(b.high), str(b.low)))
        if sweep_lo:
            rt.candidates.append(("long", bar_index, str(b.high), str(b.low)))

        for c in rt.candidates[:]:
            direction, at, extreme_s, _base = c
            extreme = Decimal(extreme_s)
            if bar_index - at > cfg.bos_window:
                rt.candidates.remove(c)
                continue
            prior = [p for p in rt.pivots if p[0] < bar_index and p[1] < at and p[2] == ("low" if direction == "short" else "high")]
            bos = bool(prior) and (b.close < prior[-1][3] if direction == "short" else b.close > prior[-1][3])
            if cfg.require_bos_after_sweep and (bar_index <= at or not bos):
                continue
            if not cfg.require_bos_after_sweep and bar_index != at:
                continue
            sid = f"sweep-{direction}-{at}"
            if sid in rt.placed_setup_ids:
                rt.candidates.remove(c)
                continue
            if direction == "short":
                impulse_hi = extreme
                impulse_lo = min(x.low for x in bars[at : bar_index + 1])
            else:
                impulse_lo = extreme
                impulse_hi = max(x.high for x in bars[at : bar_index + 1])
            order = order_from_impulse(
                "video_liquidity_sweep",
                direction,
                bar_index,
                impulse_lo,
                impulse_hi,
                cfg,
                "previous-session sweep and " + ("BOS" if cfg.require_bos_after_sweep else "rejection"),
            )
            if order:
                order.setup_id = sid
                rt.placed_setup_ids.append(sid)
                out.append(order)
            rt.candidates.remove(c)

    rt.last_bar_index = bar_index
    return rt, out


def session_sweep_orders_incremental(
    bars: list[Bar],
    cfg: VideoConfig,
    session_keys: list[str],
    runtime: SessionSweepRuntime | None = None,
) -> tuple[list[Order], SessionSweepRuntime]:
    rt = runtime or SessionSweepRuntime()
    all_orders: list[Order] = []
    for i in range(len(bars)):
        rt, chunk = session_sweep_step(rt, bars, cfg, session_keys, i)
        all_orders.extend(chunk)
    return all_orders, rt


@dataclass
class AnchorBosRuntime:
    version: int = SCHEMA_VERSION
    last_bar_index: int = -1
    pivots: list[tuple] = field(default_factory=list)
    last: dict[str, tuple | None] = field(default_factory=lambda: {"high": None, "low": None})
    used: list[tuple] = field(default_factory=list)
    placed_setup_ids: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["last"] = {k: list(v) if v else None for k, v in self.last.items()}
        return d

    @classmethod
    def from_dict(cls, raw: dict | None) -> AnchorBosRuntime:
        if not raw:
            return cls()
        last_raw = raw.get("last") or {}
        last: dict[str, tuple | None] = {}
        for k in ("high", "low"):
            v = last_raw.get(k)
            last[k] = tuple(v) if v else None
        return cls(
            version=int(raw.get("version", SCHEMA_VERSION)),
            last_bar_index=int(raw.get("last_bar_index", -1)),
            pivots=[tuple(p) for p in (raw.get("pivots") or [])],
            last=last,
            used=[tuple(u) for u in (raw.get("used") or [])],
            placed_setup_ids=list(raw.get("placed_setup_ids") or []),
        )


def anchor_bos_step(
    rt: AnchorBosRuntime,
    bars: list[Bar],
    cfg: VideoConfig,
    bar_index: int,
) -> tuple[AnchorBosRuntime, list[Order]]:
    if bar_index < 0 or bar_index >= len(bars):
        return rt, []
    if bar_index <= rt.last_bar_index:
        return rt, []

    for p in _confirm_pivots_at_bar(bars, cfg, bar_index):
        if p not in rt.pivots:
            rt.pivots.append(p)
            rt.last[p[2]] = p
    rt.pivots.sort(key=lambda x: x[0])

    out: list[Order] = []
    if bar_index < 1:
        rt.last_bar_index = bar_index
        return rt, out

    b = bars[bar_index]
    used_set = set(rt.used)
    for kind, direction in [("high", "long"), ("low", "short")]:
        anchor = rt.last[kind]
        opposite = rt.last["low" if direction == "long" else "high"]
        if anchor is None or opposite is None:
            continue
        _, anchor_j, _, level = anchor
        if (kind, anchor_j) in used_set:
            continue
        broke = (b.close > level and bars[bar_index - 1].close <= level) if direction == "long" else (
            b.close < level and bars[bar_index - 1].close >= level
        )
        if not broke:
            continue
        _, opp_j, _, opp_level = opposite
        if opp_j >= bar_index:
            continue
        sid = f"anchor-{kind}-{anchor_j}-bos-{bar_index}"
        if sid in rt.placed_setup_ids:
            continue
        if direction == "long":
            low = opp_level
            high = b.high
        else:
            low = b.low
            high = opp_level
        order = order_from_impulse(
            "video_anchor_bos",
            direction,
            bar_index,
            low,
            high,
            cfg,
            f"confirmed pivot {anchor_j} BOS; fib retracement",
        )
        if order:
            order.setup_id = sid
            rt.placed_setup_ids.append(sid)
            out.append(order)
        rt.used.append((kind, anchor_j))

    rt.last_bar_index = bar_index
    return rt, out


def anchor_bos_orders_incremental(
    bars: list[Bar],
    cfg: VideoConfig,
    runtime: AnchorBosRuntime | None = None,
) -> tuple[list[Order], AnchorBosRuntime]:
    rt = runtime or AnchorBosRuntime()
    all_orders: list[Order] = []
    for i in range(len(bars)):
        rt, chunk = anchor_bos_step(rt, bars, cfg, i)
        all_orders.extend(chunk)
    return all_orders, rt


def incremental_matches_batch_sweep(bars, cfg, session_keys) -> bool:
    from app.backtest.video_strategies import session_sweep_orders

    batch = session_sweep_orders(bars, cfg, session_keys)
    inc, _ = session_sweep_orders_incremental(bars, cfg, session_keys)
    if len(batch) != len(inc):
        return False
    bk = [(o.signal_index, o.direction, o.limit, o.setup_id) for o in batch]
    ik = [(o.signal_index, o.direction, o.limit, o.setup_id) for o in inc]
    return bk == ik


def incremental_matches_batch_anchor(bars, cfg) -> bool:
    from app.backtest.video_strategies import anchor_bos_orders

    batch = anchor_bos_orders(bars, cfg)
    inc, _ = anchor_bos_orders_incremental(bars, cfg)
    if len(batch) != len(inc):
        return False
    bk = [(o.signal_index, o.direction, o.limit, o.setup_id) for o in batch]
    ik = [(o.signal_index, o.direction, o.limit, o.setup_id) for o in inc]
    return bk == ik