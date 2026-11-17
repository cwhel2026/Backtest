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
]


async def seed_strategy_library(session: AsyncSession) -> int:
    existing = await session.execute(select(StrategyDefinition).limit(1))
    if existing.scalar_one_or_none():
        return 0

    created = 0
    for item in LIBRARY:
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