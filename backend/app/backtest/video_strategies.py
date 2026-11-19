"""Video-inspired liquidity sweep and anchor BOS strategies (research prototypes).

Ported from user-supplied reference. Orders eligible only from the bar AFTER signal.
OHLC-only fills; stop wins ambiguous collisions; slippage in execution prices only.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime
from decimal import ROUND_CEILING, ROUND_FLOOR, Decimal
from typing import Literal

from app.backtest.bars import Bar
from app.models.instrument import Instrument


def D(x) -> Decimal:
    return Decimal(str(x))


@dataclass(frozen=True)
class VideoConfig:
    tick: Decimal = D("0.25")
    multiplier: Decimal = D("5")
    commission_side: Decimal = D("0.62")
    slippage_ticks: int = 1
    risk_dollars: Decimal = D("100")
    max_contracts: int = 3
    pivot_left: int = 3
    pivot_right: int = 3
    sweep_ticks: int = 1
    stop_buffer_ticks: int = 2
    fib_retracement: Decimal = D("0.618")
    reward_risk: Decimal = D("2")
    expiry_bars: int = 12
    bos_window: int = 20
    require_bos_after_sweep: bool = True

    @classmethod
    def from_instrument(cls, instrument: Instrument, spec: dict, *, slippage_ticks: int = 1) -> VideoConfig:
        entry = spec.get("entry") or {}
        risk = spec.get("risk") or {}
        return cls(
            tick=instrument.tick_size,
            multiplier=instrument.multiplier,
            commission_side=instrument.default_commission_per_side,
            slippage_ticks=slippage_ticks,
            risk_dollars=D(risk.get("dollar_risk_per_trade", 100)),
            max_contracts=int(risk.get("max_contracts", 3)),
            pivot_left=int(entry.get("pivot_left", 3)),
            pivot_right=int(entry.get("pivot_right", 3)),
            sweep_ticks=int(entry.get("sweep_ticks", 1)),
            stop_buffer_ticks=int(entry.get("stop_buffer_ticks", 2)),
            fib_retracement=D(entry.get("fib_ratio", "0.618")),
            reward_risk=D(entry.get("reward_risk", "2")),
            expiry_bars=int(entry.get("order_expire_bars", 12)),
            bos_window=int(entry.get("bos_window", 20)),
            require_bos_after_sweep=bool(entry.get("require_bos_after_sweep", True)),
        )


@dataclass
class Order:
    strategy: str
    direction: Literal["long", "short"]
    signal_index: int
    limit: Decimal
    stop: Decimal
    target: Decimal
    expiry_index: int
    reason: str


def round_tick(px: Decimal, tick: Decimal, mode: str = "nearest") -> Decimal:
    if tick <= 0:
        raise ValueError("tick must be positive")
    r = px / tick
    if mode == "up":
        return r.to_integral_value(rounding=ROUND_CEILING) * tick
    if mode == "down":
        return r.to_integral_value(rounding=ROUND_FLOOR) * tick
    return r.quantize(Decimal("1")) * tick


def pivots(bars: list[Bar], cfg: VideoConfig):
    out = []
    for j in range(cfg.pivot_left, len(bars) - cfg.pivot_right):
        group = bars[j - cfg.pivot_left : j + cfg.pivot_right + 1]
        if bars[j].high == max(x.high for x in group) and sum(x.high == bars[j].high for x in group) == 1:
            out.append((j + cfg.pivot_right, j, "high", bars[j].high))
        if bars[j].low == min(x.low for x in group) and sum(x.low == bars[j].low for x in group) == 1:
            out.append((j + cfg.pivot_right, j, "low", bars[j].low))
    return sorted(out)


def order_from_impulse(strategy: str, direction: str, i: int, low: Decimal, high: Decimal, cfg: VideoConfig, reason: str):
    if high - low < cfg.tick * 4:
        return None
    fib = cfg.fib_retracement
    if not D("0") < fib < D("1"):
        raise ValueError("fib must be between 0 and 1")
    if direction == "long":
        limit = round_tick(high - (high - low) * fib, cfg.tick, "down")
        stop = round_tick(low - cfg.tick * cfg.stop_buffer_ticks, cfg.tick, "down")
        if limit <= stop:
            return None
        target = round_tick(limit + (limit - stop) * cfg.reward_risk, cfg.tick, "up")
    else:
        limit = round_tick(low + (high - low) * fib, cfg.tick, "up")
        stop = round_tick(high + cfg.tick * cfg.stop_buffer_ticks, cfg.tick, "up")
        if limit >= stop:
            return None
        target = round_tick(limit - (stop - limit) * cfg.reward_risk, cfg.tick, "down")
    return Order(strategy, direction, i, limit, stop, target, i + cfg.expiry_bars, reason)


def session_sweep_orders(
    bars: list[Bar],
    cfg: VideoConfig,
    session_keys: list[str],
    *,
    suppress_indices: set[int] | None = None,
) -> list[Order]:
    if len(bars) != len(session_keys):
        raise ValueError("session key mismatch")
    completed: dict[str, tuple[Decimal, Decimal]] = {}
    active_key = None
    hi = lo = None
    prev = None
    candidates: list[tuple] = []
    out: list[Order] = []
    pv = pivots(bars, cfg)
    suppress = suppress_indices or set()
    for i, b in enumerate(bars):
        if i in suppress:
            continue
        key = session_keys[i]
        if key != active_key:
            if active_key is not None:
                assert hi is not None and lo is not None
                completed[active_key] = (hi, lo)
                prev = (hi, lo)
            active_key = key
            hi = b.high
            lo = b.low
            candidates = []
        else:
            hi = max(hi, b.high)
            lo = min(lo, b.low)
        if prev is None:
            continue
        ph, pl = prev
        sweep_hi = b.high >= ph + cfg.tick * cfg.sweep_ticks and b.close < ph
        sweep_lo = b.low <= pl - cfg.tick * cfg.sweep_ticks and b.close > pl
        if sweep_hi:
            candidates.append(("short", i, b.high, b.low))
        if sweep_lo:
            candidates.append(("long", i, b.high, b.low))
        for c in candidates[:]:
            direction, at, extreme, _base = c
            if i - at > cfg.bos_window:
                candidates.remove(c)
                continue
            prior = [p for p in pv if p[0] < i and p[1] < at and p[2] == ("low" if direction == "short" else "high")]
            bos = bool(prior) and (b.close < prior[-1][3] if direction == "short" else b.close > prior[-1][3])
            if cfg.require_bos_after_sweep and (i <= at or not bos):
                continue
            if not cfg.require_bos_after_sweep and i != at:
                continue
            if direction == "short":
                impulse_hi = extreme
                impulse_lo = min(x.low for x in bars[at : i + 1])
            else:
                impulse_lo = extreme
                impulse_hi = max(x.high for x in bars[at : i + 1])
            order = order_from_impulse(
                "video_liquidity_sweep",
                direction,
                i,
                impulse_lo,
                impulse_hi,
                cfg,
                "previous-session sweep and " + ("BOS" if cfg.require_bos_after_sweep else "rejection"),
            )
            if order:
                out.append(order)
            candidates.remove(c)
    return out


def anchor_bos_orders(bars: list[Bar], cfg: VideoConfig, *, suppress_indices: set[int] | None = None) -> list[Order]:
    pv = pivots(bars, cfg)
    by_confirmation: dict[int, list] = {}
    for p in pv:
        by_confirmation.setdefault(p[0], []).append(p)
    last: dict[str, tuple | None] = {"high": None, "low": None}
    used: set[tuple] = set()
    out: list[Order] = []
    suppress = suppress_indices or set()
    for i, b in enumerate(bars):
        if i < 1:
            for p in by_confirmation.get(i, []):
                last[p[2]] = p
            continue
        if i in suppress:
            for p in by_confirmation.get(i, []):
                last[p[2]] = p
            continue
        for kind, direction in [("high", "long"), ("low", "short")]:
            anchor = last[kind]
            opposite = last["low" if direction == "long" else "high"]
            if anchor is None or opposite is None:
                continue
            _, anchor_j, _, level = anchor
            if (kind, anchor_j) in used:
                continue
            broke = (b.close > level and bars[i - 1].close <= level) if direction == "long" else (
                b.close < level and bars[i - 1].close >= level
            )
            if not broke:
                continue
            _, opp_j, _, opp_level = opposite
            if opp_j >= i:
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
                i,
                low,
                high,
                cfg,
                f"confirmed pivot {anchor_j} BOS; fib retracement",
            )
            if order:
                out.append(order)
            used.add((kind, anchor_j))
        for p in by_confirmation.get(i, []):
            last[p[2]] = p
    return out


def validate_bars(bars: list[Bar]) -> None:
    if any(b.ts >= bars[i + 1].ts for i, b in enumerate(bars[:-1])):
        raise ValueError("bars must be strictly increasing")
    if any(b.low > min(b.open, b.close) or b.high < max(b.open, b.close) for b in bars):
        raise ValueError("invalid OHLC")


def rollover_suppress_indices(
    bars: list[Bar],
    tick: Decimal,
    rollover_events: list[dict] | None = None,
    *,
    jump_ticks: int = 80,
) -> set[int]:
    """Bar indices where signals should not fire (rolls / unadjusted continuous gaps)."""
    from app.services.market_data.contract_series import detect_rollover_jumps

    suppress: set[int] = set()
    for hit in detect_rollover_jumps(bars, rollover_events or [], tick_size=tick, jump_ticks=jump_ticks):
        suppress.add(int(hit["index"]))
        if int(hit["index"]) > 0:
            suppress.add(int(hit["index"]) - 1)
    if not rollover_events:
        threshold = tick * jump_ticks
        for i in range(1, len(bars)):
            if abs(bars[i].open - bars[i - 1].close) >= threshold:
                suppress.add(i)
                suppress.add(i - 1)
    return suppress


def simulate(bars: list[Bar], orders: list[Order], cfg: VideoConfig, instrument: Instrument) -> list[dict]:
    if cfg.slippage_ticks < 0 or cfg.commission_side < 0:
        raise ValueError("invalid costs")
    from app.backtest.video_execution import run_video_orders

    ledger, _stats, _analytics = run_video_orders(bars, orders, cfg, instrument)
    return ledger


def order_to_dict(o: Order) -> dict:
    d = asdict(o)
    d["limit"] = str(d["limit"])
    d["stop"] = str(d["stop"])
    d["target"] = str(d["target"])
    return d