"""Prop-firm paper book: enroll walk-forward winners and fill trades on new bars."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from zoneinfo import ZoneInfo

from sqlalchemy import desc, select
from sqlalchemy.orm import Session

from app.backtest.bars import load_bars
from app.core.config import get_settings
from app.models.instrument import Instrument
from app.models.market_data import HistoricalDataset
from app.models.paper import PaperAccount, PaperFill, PaperSlot
from app.models.research import ResearchActivity
from app.models.strategy import StrategyDefinition, StrategyVersion
from app.services.paper_engine import ClosedFill, OpenTrade, SlotCursor, advance_slot, apply_prop_rules

CHICAGO = ZoneInfo("America/Chicago")


def _chicago_today():
    return datetime.now(CHICAGO).date()


def _dec(value: Decimal | float | int) -> float:
    return float(value)


def ensure_paper_account(session: Session) -> PaperAccount:
    account = session.execute(select(PaperAccount).order_by(PaperAccount.updated_at.desc()).limit(1)).scalar_one_or_none()
    if account:
        _roll_trading_day(account)
        return account
    settings = get_settings()
    start = Decimal(str(getattr(settings, "paper_starting_equity", 100000)))
    today = _chicago_today()
    account = PaperAccount(
        name="Prop sim $100k",
        starting_equity=start,
        equity=start,
        high_water=start,
        day_start_equity=start,
        trading_day=today,
        daily_loss_limit=Decimal(str(getattr(settings, "paper_daily_loss", 2000))),
        trailing_drawdown=Decimal(str(getattr(settings, "paper_trailing_dd", 3000))),
        profit_target=Decimal(str(getattr(settings, "paper_profit_target", 6000))),
        status="active",
    )
    session.add(account)
    session.flush()
    return account


def _roll_trading_day(account: PaperAccount) -> None:
    today = _chicago_today()
    if account.trading_day != today:
        account.trading_day = today
        account.day_start_equity = account.equity
        if account.status == "daily_lock":
            account.status = "active"
        account.updated_at = datetime.now(UTC)


def enroll_strategy(session: Session, strategy: StrategyDefinition, symbol: str) -> PaperSlot | None:
    account = ensure_paper_account(session)
    if account.status == "breached":
        return None
    existing = session.execute(
        select(PaperSlot).where(PaperSlot.strategy_id == strategy.id, PaperSlot.status == "active")
    ).scalar_one_or_none()
    if existing:
        return existing
    settings = get_settings()
    cap = int(getattr(settings, "paper_max_slots", 4) or 4)
    active = session.execute(select(PaperSlot).where(PaperSlot.status == "active")).scalars().all()
    if len(active) >= cap:
        return None
    slot = PaperSlot(
        account_id=account.id,
        strategy_id=strategy.id,
        symbol=symbol.upper(),
        status="active",
    )
    session.add(slot)
    session.add(
        ResearchActivity(
            headline=f"Paper enrolled · {strategy.name}",
            detail=f"{symbol} forward-test starts on the next new bars. Simulated prop account, not a broker.",
            meta={"strategy_id": str(strategy.id), "symbol": symbol},
        )
    )
    session.flush()
    return slot


def _latest_dataset(session: Session, symbol: str) -> HistoricalDataset | None:
    inst = session.execute(select(Instrument).where(Instrument.symbol == symbol)).scalar_one_or_none()
    if not inst:
        return None
    return session.execute(
        select(HistoricalDataset)
        .where(HistoricalDataset.instrument_id == inst.id, HistoricalDataset.timeframe == "5m")
        .order_by(desc(HistoricalDataset.downloaded_at))
        .limit(1)
    ).scalar_one_or_none()


def _apply_fill(account: PaperAccount, fill: ClosedFill) -> str:
    account.equity = Decimal(account.equity) + fill.net_pnl
    hw, status = apply_prop_rules(
        equity=Decimal(account.equity),
        high_water=Decimal(account.high_water),
        day_start=Decimal(account.day_start_equity),
        daily_loss_limit=Decimal(account.daily_loss_limit),
        trailing_drawdown=Decimal(account.trailing_drawdown),
        profit_target=Decimal(account.profit_target),
        starting_equity=Decimal(account.starting_equity),
    )
    account.high_water = hw
    account.status = status
    account.updated_at = datetime.now(UTC)
    return status


def tick_paper_book(session: Session) -> dict:
    account = ensure_paper_account(session)
    slots = session.execute(select(PaperSlot).where(PaperSlot.status == "active")).scalars().all()
    opened = 0
    closed = 0
    allow = account.status in ("active", "passed")

    for slot in slots:
        strategy = session.get(StrategyDefinition, slot.strategy_id)
        if not strategy or not strategy.current_version_id:
            continue
        version = session.get(StrategyVersion, strategy.current_version_id)
        instrument = session.get(Instrument, strategy.instrument_id)
        dataset = _latest_dataset(session, slot.symbol)
        if not version or not instrument or not dataset:
            continue
        bars = load_bars(session, dataset.id)
        had_position = slot.open_direction is not None
        cursor = SlotCursor(
            last_bar_ts=slot.last_bar_ts,
            position=OpenTrade(
                slot.open_direction,
                slot.open_qty,
                Decimal(slot.open_entry_price),
                Decimal(slot.open_stop),
                Decimal(slot.open_target),
                slot.open_entry_ts,
            )
            if slot.open_direction and slot.open_entry_price is not None and slot.open_entry_ts
            else None,
        )
        cursor, fills = advance_slot(
            version.specification,
            bars,
            instrument,
            cursor,
            allow_entries=allow and account.status != "breached",
        )
        slot.last_bar_ts = cursor.last_bar_ts
        if cursor.position:
            slot.open_direction = cursor.position.direction
            slot.open_qty = cursor.position.qty
            slot.open_entry_price = cursor.position.entry_price
            slot.open_stop = cursor.position.stop
            slot.open_target = cursor.position.target
            slot.open_entry_ts = cursor.position.entry_ts
        else:
            slot.open_direction = None
            slot.open_qty = 0
            slot.open_entry_price = None
            slot.open_stop = None
            slot.open_target = None
            slot.open_entry_ts = None
        if cursor.position and not had_position:
            opened += 1
            session.add(
                ResearchActivity(
                    headline=f"Paper entry · {strategy.name}",
                    detail=(
                        f"{slot.symbol} {cursor.position.direction} x{cursor.position.qty} "
                        f"@ {cursor.position.entry_price}"
                    ),
                    meta={"slot_id": str(slot.id)},
                )
            )
        for fill in fills:
            closed += 1
            status = _apply_fill(account, fill)
            session.add(
                PaperFill(
                    account_id=account.id,
                    slot_id=slot.id,
                    strategy_name=strategy.name,
                    symbol=slot.symbol,
                    direction=fill.direction,
                    quantity=fill.qty,
                    entry_ts=fill.entry_ts,
                    entry_price=fill.entry_price,
                    exit_ts=fill.exit_ts,
                    exit_price=fill.exit_price,
                    exit_reason=fill.exit_reason,
                    net_pnl=fill.net_pnl,
                    note=status,
                )
            )
            session.add(
                ResearchActivity(
                    headline=f"Paper exit · {strategy.name}",
                    detail=(
                        f"{slot.symbol} {fill.exit_reason} net ${float(fill.net_pnl):.2f} · "
                        f"account ${float(account.equity):.0f} ({status})"
                    ),
                    meta={"slot_id": str(slot.id), "status": status},
                )
            )
            if account.status == "breached":
                allow = False

    session.commit()
    return {"slots": len(slots), "opened": opened, "closed": closed, "status": account.status, "equity": _dec(account.equity)}


def paper_snapshot(session: Session) -> dict:
    account = ensure_paper_account(session)
    slots = session.execute(select(PaperSlot).where(PaperSlot.status == "active")).scalars().all()
    fills = session.execute(select(PaperFill).order_by(desc(PaperFill.created_at)).limit(20)).scalars().all()
    open_positions = []
    for slot in slots:
        strategy = session.get(StrategyDefinition, slot.strategy_id)
        if slot.open_direction:
            open_positions.append(
                {
                    "slot_id": str(slot.id),
                    "strategy_name": strategy.name if strategy else slot.symbol,
                    "symbol": slot.symbol,
                    "direction": slot.open_direction,
                    "quantity": slot.open_qty,
                    "entry_price": _dec(slot.open_entry_price or 0),
                    "stop": _dec(slot.open_stop or 0),
                    "target": _dec(slot.open_target or 0),
                    "entry_ts": slot.open_entry_ts.isoformat() if slot.open_entry_ts else None,
                }
            )
    day_pnl = Decimal(account.equity) - Decimal(account.day_start_equity)
    return {
        "account": {
            "name": account.name,
            "status": account.status,
            "equity": _dec(account.equity),
            "starting_equity": _dec(account.starting_equity),
            "high_water": _dec(account.high_water),
            "day_pnl": _dec(day_pnl),
            "daily_loss_limit": _dec(account.daily_loss_limit),
            "trailing_drawdown": _dec(account.trailing_drawdown),
            "profit_target": _dec(account.profit_target),
            "distance_to_target": _dec(Decimal(account.profit_target) - (Decimal(account.equity) - Decimal(account.starting_equity))),
            "trailing_room": _dec(Decimal(account.trailing_drawdown) - (Decimal(account.high_water) - Decimal(account.equity))),
        },
        "enrolled": [
            {
                "slot_id": str(s.id),
                "symbol": s.symbol,
                "strategy_name": (session.get(StrategyDefinition, s.strategy_id).name if session.get(StrategyDefinition, s.strategy_id) else s.symbol),
                "in_trade": s.open_direction is not None,
            }
            for s in slots
        ],
        "open_positions": open_positions,
        "recent_fills": [
            {
                "id": str(f.id),
                "strategy_name": f.strategy_name,
                "symbol": f.symbol,
                "direction": f.direction,
                "quantity": f.quantity,
                "exit_reason": f.exit_reason,
                "net_pnl": _dec(f.net_pnl),
                "exit_ts": f.exit_ts.isoformat(),
            }
            for f in fills
        ],
        "disclaimer": "Delayed market data, simulated fills, prop-style limits. Not a broker and not a funded account.",
    }
