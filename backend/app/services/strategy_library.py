"""Built-in declarative strategies (DSL specs only — no performance claims)."""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.enums import StrategyLifecycle
from app.models.instrument import Instrument
from app.models.strategy import StrategyDefinition, StrategyHypothesis, StrategyVersion

LIBRARY: list[dict] = [
    {
        "name": "MES 5m Opening Range Breakout",
        "symbol": "MES",
        "category": "opening_range_breakout",
        "timeframe": "5m",
        "hypothesis": "Liquidity builds at RTH open; sustained breakouts may trend intraday.",
        "spec": {
            "name": "MES 5m Opening Range Breakout",
            "instrument_symbol": "MES",
            "timeframe": "5m",
            "category": "opening_range_breakout",
            "session": {"allowed": ["RTH"], "timezone": "America/Chicago"},
            "entry": {"type": "opening_range_breakout", "range_minutes": 15, "side": "both"},
            "exit": {"stop_ticks": 20, "target_ticks": 40, "session_end_flatten": True},
            "risk": {"dollar_risk_per_trade": 75, "max_contracts": 4},
        },
    },
    {
        "name": "MES 5m EMA Trend Cross",
        "symbol": "MES",
        "category": "trend_continuation",
        "timeframe": "5m",
        "hypothesis": "Short-term momentum persistence after EMA alignment.",
        "spec": {
            "name": "MES 5m EMA Trend Cross",
            "instrument_symbol": "MES",
            "timeframe": "5m",
            "category": "trend_continuation",
            "session": {"allowed": ["RTH"], "timezone": "America/Chicago"},
            "entry": {"type": "ema_crossover", "fast_period": 8, "slow_period": 21},
            "exit": {"stop_ticks": 16, "target_ticks": 24, "session_end_flatten": True},
            "risk": {"dollar_risk_per_trade": 75, "max_contracts": 3},
        },
    },
    {
        "name": "MNQ 5m VWAP Mean Reversion",
        "symbol": "MNQ",
        "category": "vwap_mean_reversion",
        "timeframe": "5m",
        "hypothesis": "Extended deviation from session VWAP may revert during liquid hours.",
        "spec": {
            "name": "MNQ 5m VWAP Mean Reversion",
            "instrument_symbol": "MNQ",
            "timeframe": "5m",
            "category": "vwap_mean_reversion",
            "session": {"allowed": ["RTH"], "timezone": "America/Chicago"},
            "entry": {"type": "vwap_reversion", "deviation_ticks": 16},
            "exit": {"stop_ticks": 24, "target_ticks": 32, "session_end_flatten": True},
            "risk": {"dollar_risk_per_trade": 100, "max_contracts": 2},
        },
    },
    {
        "name": "MNQ 5m ORB with VWAP",
        "symbol": "MNQ",
        "category": "orb_vwap",
        "timeframe": "5m",
        "hypothesis": "RTH opening-range break only when price is on the VWAP side of the move, first 2.5h.",
        "spec": {
            "name": "MNQ 5m ORB with VWAP",
            "instrument_symbol": "MNQ",
            "timeframe": "5m",
            "category": "orb_vwap",
            "session": {"allowed": ["RTH"], "timezone": "America/Chicago"},
            "entry": {"type": "opening_range_breakout", "range_minutes": 15, "side": "both"},
            "filters": {
                "vwap_align": "with",
                "start_hhmm": "08:30",
                "end_hhmm": "11:00",
                "max_trades_per_day": 2,
            },
            "exit": {
                "stop_ticks": 16,
                "target_ticks": 24,
                "breakeven_r": 1.0,
                "max_bars": 18,
                "session_end_flatten": True,
            },
            "risk": {"dollar_risk_per_trade": 75, "max_contracts": 3},
        },
    },
    {
        "name": "MNQ 5m Killzone FVG",
        "symbol": "MNQ",
        "category": "killzone_fvg",
        "timeframe": "5m",
        "hypothesis": "FVG retests only in the NY morning window, with 15m EMA bias.",
        "spec": {
            "name": "MNQ 5m Killzone FVG",
            "instrument_symbol": "MNQ",
            "timeframe": "5m",
            "category": "killzone_fvg",
            "session": {"allowed": ["RTH"], "timezone": "America/Chicago"},
            "entry": {"type": "fair_value_gap", "min_gap_ticks": 4, "max_age_bars": 36, "side": "both"},
            "filters": {
                "start_hhmm": "08:30",
                "end_hhmm": "11:00",
                "htf": "15m",
                "htf_ema": 21,
                "max_trades_per_day": 3,
            },
            "exit": {
                "stop_ticks": 12,
                "target_ticks": 20,
                "stop_atr": 1.2,
                "target_atr": 1.8,
                "session_end_flatten": True,
            },
            "risk": {"dollar_risk_per_trade": 75, "max_contracts": 3},
        },
    },
    {
        "name": "MNQ 5m Sweep + FVG",
        "symbol": "MNQ",
        "category": "sweep_fvg",
        "timeframe": "5m",
        "hypothesis": "Liquidity sweep and FVG retest must agree within 3 bars during NY morning.",
        "spec": {
            "name": "MNQ 5m Sweep + FVG",
            "instrument_symbol": "MNQ",
            "timeframe": "5m",
            "category": "sweep_fvg",
            "session": {"allowed": ["RTH"], "timezone": "America/Chicago"},
            "entry": {
                "type": "confluence",
                "window_bars": 3,
                "all": [
                    {"type": "liquidity_sweep", "lookback": 12, "sweep_ticks": 2},
                    {"type": "fair_value_gap", "min_gap_ticks": 4, "max_age_bars": 36, "side": "both"},
                ],
            },
            "filters": {
                "start_hhmm": "08:30",
                "end_hhmm": "11:00",
                "max_trades_per_day": 2,
            },
            "exit": {
                "stop_ticks": 12,
                "target_ticks": 20,
                "breakeven_r": 1.0,
                "max_bars": 16,
                "session_end_flatten": True,
            },
            "risk": {"dollar_risk_per_trade": 75, "max_contracts": 3},
        },
    },
]

_VIDEO_SWEEP_TEMPLATE = {
    "category": "video_liquidity_sweep",
    "timeframe": "5m",
    "hypothesis": "Prior completed session H/L sweep, rejection close, optional pivot BOS, fib limit entry.",
    "entry": {
        "type": "video_liquidity_sweep",
        "pivot_left": 3,
        "pivot_right": 3,
        "sweep_ticks": 1,
        "stop_buffer_ticks": 2,
        "fib_ratio": "0.618",
        "reward_risk": "2",
        "order_expire_bars": 12,
        "bos_window": 20,
        "require_bos_after_sweep": True,
    },
    "exit": {"stop_ticks": 16, "target_ticks": 32, "session_end_flatten": False},
    "risk": {"dollar_risk_per_trade": 75, "max_contracts": 2},
}

_VIDEO_ANCHOR_TEMPLATE = {
    "category": "video_anchor_bos",
    "timeframe": "5m",
    "hypothesis": "Confirmed pivot anchor, close break vs prior bar, fib retracement limit entry.",
    "entry": {
        "type": "video_anchor_bos",
        "pivot_left": 3,
        "pivot_right": 3,
        "fib_ratio": "0.618",
        "reward_risk": "2",
        "order_expire_bars": 16,
    },
    "exit": {"stop_ticks": 20, "target_ticks": 40, "session_end_flatten": False},
    "risk": {"dollar_risk_per_trade": 75, "max_contracts": 2},
}

for _sym in ("MNQ", "MES", "MGC"):
    _sweep = {**_VIDEO_SWEEP_TEMPLATE}
    _sweep["name"] = f"{_sym} 5m Video Liquidity Sweep"
    _sweep["symbol"] = _sym
    _sweep["spec"] = {
        "name": _sweep["name"],
        "instrument_symbol": _sym,
        "timeframe": "5m",
        "category": _VIDEO_SWEEP_TEMPLATE["category"],
        "session": {"allowed": ["RTH"], "timezone": "America/Chicago"},
        "entry": dict(_VIDEO_SWEEP_TEMPLATE["entry"]),
        "exit": dict(_VIDEO_SWEEP_TEMPLATE["exit"]),
        "risk": dict(_VIDEO_SWEEP_TEMPLATE["risk"]),
    }
    LIBRARY.append(_sweep)

    _anchor = {**_VIDEO_ANCHOR_TEMPLATE}
    _anchor["name"] = f"{_sym} 5m Video Anchor BOS"
    _anchor["symbol"] = _sym
    _anchor["spec"] = {
        "name": _anchor["name"],
        "instrument_symbol": _sym,
        "timeframe": "5m",
        "category": _VIDEO_ANCHOR_TEMPLATE["category"],
        "session": {"allowed": ["RTH"], "timezone": "America/Chicago"},
        "entry": dict(_VIDEO_ANCHOR_TEMPLATE["entry"]),
        "exit": dict(_VIDEO_ANCHOR_TEMPLATE["exit"]),
        "risk": dict(_VIDEO_ANCHOR_TEMPLATE["risk"]),
    }
    LIBRARY.append(_anchor)


async def seed_strategy_library(session: AsyncSession) -> int:
    created = 0
    for item in LIBRARY:
        already = (
            await session.execute(select(StrategyDefinition).where(StrategyDefinition.name == item["name"]))
        ).scalar_one_or_none()
        if already:
            continue
        inst = (
            await session.execute(select(Instrument).where(Instrument.symbol == item["symbol"]))
        ).scalar_one_or_none()
        if not inst:
            continue
        hypo = StrategyHypothesis(
            instrument_id=inst.id,
            title=item["name"],
            category=item["category"],
            economic_rationale=item["hypothesis"],
            created_by="library",
        )
        session.add(hypo)
        await session.flush()
        defn = StrategyDefinition(
            hypothesis_id=hypo.id,
            name=item["name"],
            instrument_id=inst.id,
            timeframe=item["timeframe"],
            category=item["category"],
            lifecycle=StrategyLifecycle.RESEARCHING,
        )
        session.add(defn)
        await session.flush()
        ver = StrategyVersion(
            strategy_id=defn.id,
            version_number=1,
            specification=item["spec"],
            changelog="Initial library version",
        )
        session.add(ver)
        await session.flush()
        defn.current_version_id = ver.id
        created += 1
    await session.flush()
    return created