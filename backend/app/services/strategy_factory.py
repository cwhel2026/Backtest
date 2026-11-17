"""Create strategy definitions + versioned DSL specs."""

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session

from app.backtest.dsl import validate_spec
from app.models.enums import StrategyLifecycle
from app.models.instrument import Instrument
from app.models.strategy import StrategyDefinition, StrategyHypothesis, StrategyVersion


def _normalize_spec(spec: dict, instrument_symbol: str, timeframe: str) -> dict:
    out = dict(spec)
    out["instrument_symbol"] = instrument_symbol.upper()
    out["timeframe"] = timeframe
    if "session" not in out:
        out["session"] = {"allowed": ["RTH"], "timezone": "America/Chicago"}
    if "category" not in out:
        out["category"] = out.get("entry", {}).get("type", "custom")
    if "name" not in out:
        out["name"] = f"{instrument_symbol} {timeframe} {out['category']}"
    return out


def create_strategy_sync(
    session: Session,
    *,
    specification: dict,
    economic_rationale: str,
    created_by: str,
) -> StrategyDefinition:
    spec = _normalize_spec(
        specification,
        specification.get("instrument_symbol", ""),
        specification.get("timeframe", "5m"),
    )
    errors = validate_spec(spec)
    if errors:
        raise ValueError("; ".join(errors))

    inst = session.execute(
        select(Instrument).where(Instrument.symbol == spec["instrument_symbol"])
    ).scalar_one_or_none()
    if not inst:
        raise ValueError(f"Unknown instrument {spec['instrument_symbol']}")

    hypo = StrategyHypothesis(
        instrument_id=inst.id,
        title=spec["name"],
        category=spec.get("category", "custom"),
        economic_rationale=economic_rationale,
        created_by=created_by,
    )
    session.add(hypo)
    session.flush()

    defn = StrategyDefinition(
        hypothesis_id=hypo.id,
        name=spec["name"],
        instrument_id=inst.id,
        timeframe=spec["timeframe"],
        category=spec.get("category", "custom"),
        lifecycle=StrategyLifecycle.RESEARCHING,
    )
    session.add(defn)
    session.flush()

    ver = StrategyVersion(
        strategy_id=defn.id,
        version_number=1,
        specification=spec,
        changelog=f"Created by {created_by}",
    )
    session.add(ver)
    session.flush()
    defn.current_version_id = ver.id
    session.flush()
    return defn


async def create_strategy_async(
    session: AsyncSession,
    *,
    specification: dict,
    economic_rationale: str,
    created_by: str,
) -> StrategyDefinition:
    spec = _normalize_spec(
        specification,
        specification.get("instrument_symbol", ""),
        specification.get("timeframe", "5m"),
    )
    errors = validate_spec(spec)
    if errors:
        raise ValueError("; ".join(errors))

    inst = (
        await session.execute(select(Instrument).where(Instrument.symbol == spec["instrument_symbol"]))
    ).scalar_one_or_none()
    if not inst:
        raise ValueError(f"Unknown instrument {spec['instrument_symbol']}")

    hypo = StrategyHypothesis(
        instrument_id=inst.id,
        title=spec["name"],
        category=spec.get("category", "custom"),
        economic_rationale=economic_rationale,
        created_by=created_by,
    )
    session.add(hypo)
    await session.flush()

    defn = StrategyDefinition(
        hypothesis_id=hypo.id,
        name=spec["name"],
        instrument_id=inst.id,
        timeframe=spec["timeframe"],
        category=spec.get("category", "custom"),
        lifecycle=StrategyLifecycle.RESEARCHING,
    )
    session.add(defn)
    await session.flush()

    ver = StrategyVersion(
        strategy_id=defn.id,
        version_number=1,
        specification=spec,
        changelog=f"Created by {created_by}",
    )
    session.add(ver)
    await session.flush()
    defn.current_version_id = ver.id
    await session.flush()
    return defn


async def clone_strategy_async(
    session: AsyncSession,
    *,
    strategy_id: uuid.UUID,
    new_name: str | None,
    created_by: str,
) -> StrategyDefinition:
    defn = await session.get(StrategyDefinition, strategy_id)
    if not defn or not defn.current_version_id:
        raise ValueError("Strategy not found or has no version")
    ver = await session.get(StrategyVersion, defn.current_version_id)
    if not ver:
        raise ValueError("Strategy version missing")

    spec = dict(ver.specification)
    spec["name"] = new_name or f"{defn.name} (copy)"
    hypo = await session.get(StrategyHypothesis, defn.hypothesis_id) if defn.hypothesis_id else None
    rationale = hypo.economic_rationale if hypo else spec["name"]
    return await create_strategy_async(
        session,
        specification=spec,
        economic_rationale=f"Cloned from {defn.id}: {rationale}",
        created_by=created_by,
    )