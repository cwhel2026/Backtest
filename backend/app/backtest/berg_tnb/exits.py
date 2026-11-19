"""Labelled research exit profiles — not claimed as PDF-universal rules."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from app.backtest.berg_tnb.fib import round_tick
from app.backtest.berg_tnb.types import BergTnbSetup


@dataclass
class ExitProfile:
    key: str
    label: str
    reward_risk: Decimal | None = None
    stop_ticks: int | None = None
    target_ticks: int | None = None
    time_stop_bars: int | None = None
    swing_buffer_ticks: int = 2


PROFILES: dict[str, ExitProfile] = {
    "structural_rr": ExitProfile("structural_rr", "Structural stop + fixed R multiple", reward_risk=Decimal("2")),
    "fixed_ticks": ExitProfile("fixed_ticks", "Fixed tick stop/target", stop_ticks=20, target_ticks=40),
    "swing": ExitProfile("swing", "Swing extreme stop + RR", reward_risk=Decimal("1.5"), swing_buffer_ticks=2),
    "time_exit": ExitProfile("time_exit", "Time-based exit (bars)", time_stop_bars=24),
}


def resolve_exit_prices(
    profile_key: str,
    *,
    direction: str,
    entry: Decimal,
    structural_stop: Decimal,
    tick: Decimal,
) -> tuple[Decimal, Decimal, str]:
    p = PROFILES.get(profile_key, PROFILES["structural_rr"])
    if profile_key == "fixed_ticks" and p.stop_ticks and p.target_ticks:
        if direction == "long":
            stop = entry - tick * p.stop_ticks
            target = entry + tick * p.target_ticks
        else:
            stop = entry + tick * p.stop_ticks
            target = entry - tick * p.target_ticks
        return stop, target, p.label
    if p.reward_risk:
        risk = abs(entry - structural_stop)
        if direction == "long":
            target = entry + risk * p.reward_risk
        else:
            target = entry - risk * p.reward_risk
        return structural_stop, round_tick(target, tick, "up" if direction == "long" else "down"), p.label
    if p.time_stop_bars:
        if direction == "long":
            return structural_stop, entry + tick * 40, p.label
        return structural_stop, entry - tick * 40, p.label
    raise ValueError(f"Unknown exit profile {profile_key}")