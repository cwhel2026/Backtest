"""Prop-firm paper book: enroll walk-forward winners and fill trades on new bars."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from zoneinfo import ZoneInfo

from sqlalchemy import desc, select
from sqlalchemy.orm import Session

from app.backtest.bars import load_bars
from app.core.config import get_settings
from app.models.backtest import BacktestRun
from app.models.instrument import Instrument
from app.models.market_data import HistoricalDataset
from app.models.paper import PaperAccount, PaperFill, PaperSlot
from app.models.research import ResearchActivity
from app.models.strategy import StrategyDefinition, StrategyVersion
from app.services.leaderboard import leaderboard_entries_sync
from app.services.market_data.dataset_gc import reclaim_search_disk
from app.services.market_data.live_feed import refresh_live_bars_resilient
from app.services.paper_engine import ClosedFill, OpenTrade, SlotCursor, advance_slot, apply_prop_rules
from app.util.db_errors import compact_error, is_disk_full

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


def strategy_fingerprint(spec: dict | None) -> str:
    """Same entry+ATR stop profile on one market counts as one live slot."""
    spec = spec or {}
    entry = spec.get("entry") or {}
    exit_spec = spec.get("exit") or {}
    parts = [
        str(spec.get("instrument_symbol") or "").upper(),
        str(spec.get("timeframe") or "5m"),
        str(spec.get("category") or ""),
        str(entry.get("type") or ""),
        str(entry.get("fast_period") or ""),
        str(entry.get("slow_period") or ""),
        str(exit_spec.get("stop_atr") or ""),
        str(exit_spec.get("target_atr") or ""),
        str(exit_spec.get("stop_ticks") or ""),
        str(exit_spec.get("target_ticks") or ""),
    ]
    return "|".join(parts)


def _spec_for_strategy(session: Session, strategy: StrategyDefinition) -> dict:
    if not strategy.current_version_id:
        return {}
    version = session.get(StrategyVersion, strategy.current_version_id)
    return dict(version.specification or {}) if version else {}


def enroll_strategy(session: Session, strategy: StrategyDefinition, symbol: str) -> PaperSlot | None:
    account = ensure_paper_account(session)
    if account.status == "breached":
        return None
    existing = session.execute(
        select(PaperSlot).where(PaperSlot.strategy_id == strategy.id, PaperSlot.status == "active")
    ).scalar_one_or_none()
    if existing:
        return existing
    spec = _spec_for_strategy(session, strategy)
    fp = strategy_fingerprint(spec)
    settings = get_settings()
    cap = int(getattr(settings, "paper_max_slots", 8) or 8)
    active = session.execute(select(PaperSlot).where(PaperSlot.status == "active")).scalars().all()
    if len(active) >= cap:
        return None
    for slot in active:
        other = session.get(StrategyDefinition, slot.strategy_id)
        if other and strategy_fingerprint(_spec_for_strategy(session, other)) == fp:
            return slot
    timeframe = str(spec.get("timeframe") or strategy.timeframe or "5m")
    slot = PaperSlot(
        account_id=account.id,
        strategy_id=strategy.id,
        symbol=symbol.upper(),
        timeframe=timeframe,
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


def _latest_dataset(session: Session, symbol: str, timeframe: str = "5m") -> HistoricalDataset | None:
    inst = session.execute(select(Instrument).where(Instrument.symbol == symbol)).scalar_one_or_none()
    if not inst:
        return None
    return session.execute(
        select(HistoricalDataset)
        .where(HistoricalDataset.instrument_id == inst.id, HistoricalDataset.timeframe == timeframe)
        .order_by(desc(HistoricalDataset.downloaded_at))
        .limit(1)
    ).scalar_one_or_none()


def enroll_verified_keepers(session: Session) -> int:
    """Enroll full-sample keepers (including search near-misses that still pass the prop screen)."""
    added = 0
    for row in leaderboard_entries_sync(session, limit=24, profitable_only=True):
        if not row.get("passes_prop_screen"):
            continue
        strategy = session.get(StrategyDefinition, row["strategy_id"])
        if not strategy:
            continue
        before = session.execute(
            select(PaperSlot).where(PaperSlot.strategy_id == strategy.id, PaperSlot.status == "active")
        ).scalar_one_or_none()
        slot = enroll_strategy(session, strategy, row["symbol"])
        if slot and before is None and slot.strategy_id == strategy.id:
            added += 1
    return added


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


def tick_paper_book(session: Session, *, refresh_data: bool = True) -> dict:
    account = ensure_paper_account(session)
    enrolled_new = enroll_verified_keepers(session)
    slots = session.execute(select(PaperSlot).where(PaperSlot.status == "active")).scalars().all()
    opened = 0
    closed = 0
    refreshed = 0
    allow = account.status in ("active", "passed")
    refresh_errors: dict[tuple[str, str], str] = {}

    if refresh_data:
        try:
            reclaim_search_disk(session)
            session.flush()
        except Exception as exc:
            session.rollback()
            account = ensure_paper_account(session)
            enrolled_new = enroll_verified_keepers(session)
            slots = session.execute(select(PaperSlot).where(PaperSlot.status == "active")).scalars().all()
            if is_disk_full(exc):
                refresh_errors[("_", "_")] = compact_error(exc)
        keys: list[tuple[str, str]] = []
        seen: set[tuple[str, str]] = set()
        for slot in slots:
            key = (slot.symbol.upper(), slot.timeframe or "5m")
            if key in seen:
                continue
            seen.add(key)
            keys.append(key)
        for symbol, tf in keys:
            try:
                refresh_live_bars_resilient(session, symbol, tf)
                session.flush()
                refreshed += 1
            except Exception as exc:
                session.rollback()
                refresh_errors[(symbol, tf)] = compact_error(exc)
                account = ensure_paper_account(session)
                slots = session.execute(select(PaperSlot).where(PaperSlot.status == "active")).scalars().all()

    account = ensure_paper_account(session)
    slots = session.execute(select(PaperSlot).where(PaperSlot.status == "active")).scalars().all()
    allow = account.status in ("active", "passed")

    for slot in slots:
        strategy = session.get(StrategyDefinition, slot.strategy_id)
        if not strategy or not strategy.current_version_id:
            continue
        version = session.get(StrategyVersion, strategy.current_version_id)
        instrument = session.get(Instrument, strategy.instrument_id)
        tf = slot.timeframe or (version.specification or {}).get("timeframe") or strategy.timeframe or "5m"
        slot.timeframe = tf
        dataset = _latest_dataset(session, slot.symbol, tf)
        feed_err = refresh_errors.get((slot.symbol.upper(), tf))
        if not version or not instrument or not dataset:
            slot.last_error = feed_err or slot.last_error or f"No {tf} dataset for {slot.symbol}"
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
                int(slot.open_bars_held or 0),
                Decimal(slot.open_initial_risk or 0),
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
        slot.last_refresh_at = datetime.now(UTC)
        slot.last_error = feed_err
        if cursor.position:
            slot.open_direction = cursor.position.direction
            slot.open_qty = cursor.position.qty
            slot.open_entry_price = cursor.position.entry_price
            slot.open_stop = cursor.position.stop
            slot.open_target = cursor.position.target
            slot.open_entry_ts = cursor.position.entry_ts
            slot.open_bars_held = cursor.position.bars_held
            slot.open_initial_risk = cursor.position.initial_risk
        else:
            slot.open_direction = None
            slot.open_qty = 0
            slot.open_entry_price = None
            slot.open_stop = None
            slot.open_target = None
            slot.open_entry_ts = None
            slot.open_bars_held = 0
            slot.open_initial_risk = None
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

    try:
        session.commit()
    except Exception as exc:
        session.rollback()
        if is_disk_full(exc):
            try:
                reclaim_search_disk(session)
                session.commit()
            except Exception:
                session.rollback()
        raise RuntimeError(compact_error(exc)) from exc
    return {
        "slots": len(slots),
        "opened": opened,
        "closed": closed,
        "refreshed": refreshed,
        "enrolled_new": enrolled_new,
        "status": account.status,
        "equity": _dec(account.equity),
        "feed_errors": [{ "symbol": s, "timeframe": tf, "error": err } for (s, tf), err in refresh_errors.items() if s != "_"],
    }


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
                    "bars_held": slot.open_bars_held,
                    "timeframe": slot.timeframe,
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
        "enrolled": [_slot_summary(session, s) for s in slots],
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
        "heartbeat": datetime.now(UTC).isoformat(),
    }


def _slot_summary(session: Session, slot: PaperSlot) -> dict:
    strategy = session.get(StrategyDefinition, slot.strategy_id)
    fills = session.execute(select(PaperFill).where(PaperFill.slot_id == slot.id)).scalars().all()
    nets = [Decimal(f.net_pnl) for f in fills]
    wins = [n for n in nets if n > 0]
    baseline = None
    run = session.execute(
        select(BacktestRun)
        .where(BacktestRun.strategy_id == slot.strategy_id, BacktestRun.status == "completed")
        .order_by(desc(BacktestRun.completed_at))
        .limit(1)
    ).scalar_one_or_none()
    if run and isinstance(run.metrics, dict):
        baseline = {
            "net": round(float(run.metrics.get("total_net_profit") or 0), 2),
            "win_rate_pct": round(float(run.metrics.get("win_rate") or 0) * 100, 1)
            if run.metrics.get("win_rate") is not None
            else None,
            "trades": int(run.metrics.get("trade_count") or 0),
            "expectancy": round(float(run.metrics.get("expectancy_per_trade") or 0), 2)
            if run.metrics.get("expectancy_per_trade") is not None
            else None,
        }
    return {
        "slot_id": str(slot.id),
        "symbol": slot.symbol,
        "timeframe": slot.timeframe,
        "strategy_name": strategy.name if strategy else slot.symbol,
        "strategy_id": str(slot.strategy_id),
        "in_trade": slot.open_direction is not None,
        "last_bar_ts": slot.last_bar_ts.isoformat() if slot.last_bar_ts else None,
        "last_refresh_at": slot.last_refresh_at.isoformat() if slot.last_refresh_at else None,
        "last_error": slot.last_error,
        "paper_trades": len(nets),
        "paper_net": _dec(sum(nets, Decimal(0))),
        "paper_win_rate_pct": round(100.0 * len(wins) / len(nets), 1) if nets else None,
        "baseline": baseline,
    }
