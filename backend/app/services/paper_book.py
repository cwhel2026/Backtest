"""Prop-firm paper book: enroll walk-forward winners and fill trades on new bars."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from zoneinfo import ZoneInfo

from sqlalchemy import desc, select
from sqlalchemy.orm import Session

from app.backtest.bars import load_bars
from app.core.config import get_settings
from app.models.backtest import BacktestRun, OhlcvBar
from app.models.instrument import Instrument
from app.models.market_data import HistoricalDataset
from app.models.paper import PaperAccount, PaperFill, PaperSlot
from app.models.research import ResearchActivity
from app.models.strategy import StrategyDefinition, StrategyVersion
from app.services.leaderboard import leaderboard_entries_sync
from app.services.market_data.live_feed import refresh_live_bars
from app.services.paper_engine import ClosedFill, OpenTrade, SlotCursor, advance_slot, apply_prop_rules

CHICAGO = ZoneInfo("America/Chicago")
TICK_INTERVAL_SEC = 60
TF_SECONDS = {"1m": 60, "5m": 300, "15m": 900, "1h": 3600}


def _chicago_today():
    return datetime.now(CHICAGO).date()


def globex_session(now: datetime | None = None) -> dict:
    """CME equity-index Globex window in America/Chicago."""
    clock = now or datetime.now(CHICAGO)
    if clock.tzinfo is None:
        clock = clock.replace(tzinfo=UTC)
    clock = clock.astimezone(CHICAGO)
    weekday = clock.weekday()
    minutes = clock.hour * 60 + clock.minute
    open_flag = True
    if weekday == 5:
        state, label, open_flag = "closed", "Weekend — Globex closed", False
    elif weekday == 6 and minutes < 17 * 60:
        state, label, open_flag = "closed", "Weekend — Globex opens Sunday 17:00 CT", False
    elif weekday == 4 and minutes >= 16 * 60:
        state, label, open_flag = "closed", "Weekend — Globex closed Friday 16:00 CT", False
    elif 16 * 60 <= minutes < 17 * 60:
        state, label, open_flag = "halt", "Daily halt 16:00–17:00 CT", False
    elif (8 * 60 + 30) <= minutes < (15 * 60 + 10):
        state, label = "rth", "RTH open · scanning for entries"
    else:
        state, label = "globex", "Globex electronic session · scanning"
    return {
        "state": state,
        "label": label,
        "open": open_flag,
        "chicago": clock.strftime("%H:%M:%S CT"),
        "weekday": clock.strftime("%A"),
    }


def _aware(ts: datetime | None) -> datetime | None:
    if ts is None:
        return None
    return ts.replace(tzinfo=UTC) if ts.tzinfo is None else ts.astimezone(UTC)


def _age_sec(ts: datetime | None, now: datetime | None = None) -> int | None:
    aware = _aware(ts)
    if aware is None:
        return None
    clock = now or datetime.now(UTC)
    if clock.tzinfo is None:
        clock = clock.replace(tzinfo=UTC)
    return max(0, int((clock.astimezone(UTC) - aware).total_seconds()))


def _parse_iso(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def scan_headline(
    *,
    slot_count: int,
    opened: int,
    closed: int,
    enrolled_new: int,
    watches: list[dict],
    session: dict,
) -> str:
    prefix = f"Enrolled {enrolled_new} keeper{'s' if enrolled_new != 1 else ''}. " if enrolled_new else ""
    if slot_count == 0:
        return "No keepers on the book yet — each scan auto-enrolls prop-screen winners."
    if opened or closed:
        return prefix + f"Scan complete: {opened} new entries, {closed} exits."
    errors = [w for w in watches if w.get("error")]
    prints = [w for w in watches if w.get("last_close") is not None]
    in_trade = [w for w in watches if w.get("in_trade")]
    if errors and not prints:
        return prefix + f"Feed error: {str(errors[0].get('error') or '')[:120]}"
    if in_trade:
        trade = in_trade[0]
        return prefix + (
            f"Managing {trade.get('symbol')} {trade.get('direction') or 'open'} "
            f"· still scanning remaining slots for entries."
        )
    if prints:
        watch = prints[0]
        symbol = watch.get("symbol")
        tf = watch.get("timeframe")
        last_close = watch.get("last_close")
        if any(w.get("armed") for w in watches):
            return prefix + (
                f"Armed {symbol} {tf} at {last_close} — the next new bar will be evaluated for entries."
            )
        new_bars = sum(int(w.get("new_bars") or 0) for w in watches)
        if new_bars:
            return prefix + (
                f"Scanned {new_bars} new {tf} bar(s) on {symbol} @ {last_close} — no entry this pass."
            )
        return prefix + f"Caught up on {symbol} {tf} @ {last_close} — watching for the next bar."
    if not session.get("open"):
        return prefix + f"{session.get('label')} — scanner stays armed and will pull bars when Globex reopens."
    return prefix + "Scanner is live. Waiting for the first bars to land."


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
    feeds: dict[tuple[str, str], dict] = {}
    watches: list[dict] = []

    if refresh_data:
        seen: set[tuple[str, str]] = set()
        for slot in slots:
            tf = slot.timeframe or "5m"
            key = (slot.symbol.upper(), tf)
            if key in seen:
                continue
            seen.add(key)
            try:
                result = refresh_live_bars(session, slot.symbol, tf)
                feeds[key] = result
                refreshed += 1
            except Exception as exc:
                feeds[key] = {"error": str(exc)[:400]}
                slot.last_error = str(exc)[:400]
                session.add(slot)

    for slot in slots:
        strategy = session.get(StrategyDefinition, slot.strategy_id)
        if not strategy or not strategy.current_version_id:
            continue
        version = session.get(StrategyVersion, strategy.current_version_id)
        instrument = session.get(Instrument, strategy.instrument_id)
        tf = slot.timeframe or (version.specification or {}).get("timeframe") or strategy.timeframe or "5m"
        slot.timeframe = tf
        feed = feeds.get((slot.symbol.upper(), tf), {})
        dataset = _latest_dataset(session, slot.symbol, tf)
        if not version or not instrument or not dataset:
            slot.last_error = slot.last_error or f"No {tf} dataset for {slot.symbol}"
            watches.append(
                {
                    "slot_id": str(slot.id),
                    "symbol": slot.symbol,
                    "timeframe": tf,
                    "strategy_name": strategy.name if strategy else slot.symbol,
                    "state": "error",
                    "error": slot.last_error,
                    "in_trade": slot.open_direction is not None,
                    "feed_source": feed.get("source"),
                }
            )
            continue
        bars = load_bars(session, dataset.id)
        prev_ts = slot.last_bar_ts
        last = bars[-1] if bars else None
        new_count = sum(1 for b in bars if prev_ts is None or b.ts > prev_ts)
        first_arm = prev_ts is None and last is not None
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
        slot.last_error = None
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
        just_opened = bool(cursor.position and not had_position)
        if just_opened:
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
        if slot.last_error:
            state = "error"
        elif cursor.position:
            state = "in_trade"
        elif first_arm:
            state = "armed"
        elif new_count == 0:
            state = "watching"
        else:
            state = "scanned"
        watches.append(
            {
                "slot_id": str(slot.id),
                "symbol": slot.symbol,
                "timeframe": tf,
                "strategy_name": strategy.name,
                "state": state,
                "bars": len(bars),
                "new_bars": 0 if first_arm else new_count,
                "armed": first_arm,
                "last_bar_ts": last.ts.isoformat() if last else None,
                "last_open": float(last.open) if last else None,
                "last_high": float(last.high) if last else None,
                "last_low": float(last.low) if last else None,
                "last_close": float(last.close) if last else None,
                "last_volume": int(last.volume) if last else 0,
                "feed_source": feed.get("source"),
                "bars_added": feed.get("added"),
                "in_trade": cursor.position is not None,
                "direction": cursor.position.direction if cursor.position else None,
                "opened": 1 if just_opened else 0,
                "closed": len(fills),
                "error": slot.last_error,
            }
        )

    market = globex_session()
    headline = scan_headline(
        slot_count=len(slots),
        opened=opened,
        closed=closed,
        enrolled_new=enrolled_new,
        watches=watches,
        session=market,
    )
    now = datetime.now(UTC)
    previous = account.last_scan if isinstance(account.last_scan, dict) else {}
    history = list(previous.get("history") or [])
    history.insert(
        0,
        {
            "at": now.isoformat(),
            "headline": headline,
            "opened": opened,
            "closed": closed,
            "refreshed": refreshed,
            "enrolled_new": enrolled_new,
            "new_bars": sum(int(w.get("new_bars") or 0) for w in watches),
            "slots": len(slots),
        },
    )
    account.last_scan = {
        "at": now.isoformat(),
        "headline": headline,
        "opened": opened,
        "closed": closed,
        "refreshed": refreshed,
        "enrolled_new": enrolled_new,
        "slots": len(slots),
        "session": market,
        "watches": watches,
        "history": history[:12],
    }
    account.updated_at = now
    session.commit()
    return {
        "slots": len(slots),
        "opened": opened,
        "closed": closed,
        "refreshed": refreshed,
        "enrolled_new": enrolled_new,
        "status": account.status,
        "equity": _dec(account.equity),
        "headline": headline,
        "session": market,
        "watches": watches,
        "at": now.isoformat(),
    }


def _latest_print(session: Session, symbol: str, timeframe: str) -> dict | None:
    dataset = _latest_dataset(session, symbol, timeframe)
    if not dataset:
        return None
    bar = session.execute(
        select(OhlcvBar).where(OhlcvBar.dataset_id == dataset.id).order_by(desc(OhlcvBar.ts)).limit(1)
    ).scalar_one_or_none()
    if not bar:
        return None
    source = ""
    if isinstance(dataset.meta, dict):
        source = str(dataset.meta.get("source") or dataset.source_uri or "")
    else:
        source = str(dataset.source_uri or "")
    return {
        "ts": bar.ts.isoformat(),
        "open": float(bar.open),
        "high": float(bar.high),
        "low": float(bar.low),
        "close": float(bar.close),
        "volume": int(bar.volume or 0),
        "row_count": int(dataset.row_count or 0),
        "coverage_end": dataset.coverage_end.isoformat() if dataset.coverage_end else None,
        "source": source,
        "age_sec": _age_sec(bar.ts),
    }


def _unrealized(slot: PaperSlot, last_close: float | None, multiplier: Decimal | None) -> float | None:
    if last_close is None or not slot.open_direction or slot.open_entry_price is None or not multiplier:
        return None
    qty = Decimal(slot.open_qty or 0)
    entry = Decimal(slot.open_entry_price)
    close = Decimal(str(last_close))
    diff = close - entry if slot.open_direction == "long" else entry - close
    return round(float(diff * multiplier * qty), 2)


def scanner_payload(
    *,
    last_scan: dict | None,
    enrolled: list[dict],
    now: datetime | None = None,
) -> dict:
    clock = now or datetime.now(UTC)
    last = last_scan if isinstance(last_scan, dict) else {}
    last_at = _parse_iso(last.get("at"))
    age = _age_sec(last_at, clock)
    live = age is not None and age <= 90
    stale = age is not None and age > 180
    market = globex_session(clock)
    watching = [row for row in enrolled if not row.get("in_trade") and not row.get("last_error")]
    trading = [row for row in enrolled if row.get("in_trade")]
    errors = [row for row in enrolled if row.get("last_error")]
    if not enrolled:
        status = "empty"
    elif errors and not any(row.get("last_close") is not None for row in enrolled):
        status = "error"
    elif stale:
        status = "stale"
    elif trading:
        status = "in_trade"
    elif live or last:
        status = "scanning"
    else:
        status = "armed"
    headline = last.get("headline") or scan_headline(
        slot_count=len(enrolled),
        opened=int(last.get("opened") or 0),
        closed=int(last.get("closed") or 0),
        enrolled_new=int(last.get("enrolled_new") or 0),
        watches=enrolled,
        session=market,
    )
    next_due = max(0, TICK_INTERVAL_SEC - age) if age is not None else None
    return {
        "status": status,
        "live": live,
        "stale": stale,
        "tick_interval_sec": TICK_INTERVAL_SEC,
        "last_scan_at": last.get("at"),
        "last_scan_age_sec": age,
        "next_scan_sec": next_due,
        "headline": headline,
        "session": market,
        "opened": int(last.get("opened") or 0),
        "closed": int(last.get("closed") or 0),
        "refreshed": int(last.get("refreshed") or 0),
        "enrolled_new": int(last.get("enrolled_new") or 0),
        "new_bars": sum(int(w.get("new_bars") or 0) for w in (last.get("watches") or [])),
        "history": last.get("history") or [],
        "watching_count": len(watching),
        "in_trade_count": len(trading),
        "slot_count": len(enrolled),
        "feed_note": (
            "Yahoo/FinzData prints are delayed (~15m). The scanner still evaluates every new bar; "
            "it does not replay history on first arm."
        ),
    }


def paper_snapshot(session: Session) -> dict:
    account = ensure_paper_account(session)
    slots = session.execute(select(PaperSlot).where(PaperSlot.status == "active")).scalars().all()
    fills = session.execute(select(PaperFill).order_by(desc(PaperFill.created_at)).limit(20)).scalars().all()
    enrolled = [_slot_summary(session, s) for s in slots]
    last_scan = account.last_scan if isinstance(account.last_scan, dict) else {}
    watch_by_id = {str(w.get("slot_id")): w for w in (last_scan.get("watches") or []) if w.get("slot_id")}
    open_positions = []
    for slot, row in zip(slots, enrolled, strict=False):
        watch = watch_by_id.get(str(slot.id), {})
        if watch:
            row["state"] = watch.get("state") or row.get("state")
            row["new_bars"] = watch.get("new_bars", row.get("new_bars"))
            row["armed"] = watch.get("armed", row.get("armed"))
            row["feed_source"] = watch.get("feed_source") or row.get("feed_source")
        if slot.open_direction:
            open_positions.append(
                {
                    "slot_id": str(slot.id),
                    "strategy_name": row["strategy_name"],
                    "symbol": slot.symbol,
                    "direction": slot.open_direction,
                    "quantity": slot.open_qty,
                    "entry_price": _dec(slot.open_entry_price or 0),
                    "stop": _dec(slot.open_stop or 0),
                    "target": _dec(slot.open_target or 0),
                    "entry_ts": slot.open_entry_ts.isoformat() if slot.open_entry_ts else None,
                    "bars_held": slot.open_bars_held,
                    "timeframe": slot.timeframe,
                    "last_close": row.get("last_close"),
                    "unrealized": row.get("unrealized"),
                    "last_bar_ts": row.get("last_bar_ts"),
                }
            )
    now = datetime.now(UTC)
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
        "scanner": scanner_payload(last_scan=last_scan, enrolled=enrolled, now=now),
        "enrolled": enrolled,
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
        "heartbeat": now.isoformat(),
    }


def _slot_summary(session: Session, slot: PaperSlot) -> dict:
    strategy = session.get(StrategyDefinition, slot.strategy_id)
    instrument = session.get(Instrument, strategy.instrument_id) if strategy else None
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
    tf = slot.timeframe or "5m"
    last_print = _latest_print(session, slot.symbol, tf)
    last_close = last_print["close"] if last_print else None
    last_bar_ts = last_print["ts"] if last_print else (slot.last_bar_ts.isoformat() if slot.last_bar_ts else None)
    caught_up = bool(
        last_print and slot.last_bar_ts and _aware(slot.last_bar_ts) and last_print["ts"].startswith(_aware(slot.last_bar_ts).isoformat()[:19])
    )
    if slot.last_error:
        state = "error"
    elif slot.open_direction:
        state = "in_trade"
    elif slot.last_bar_ts is None:
        state = "armed"
    elif caught_up:
        state = "watching"
    else:
        state = "scanning"
    next_bar_sec = None
    if last_print and last_print.get("ts"):
        bar_ts = _parse_iso(last_print["ts"])
        step = TF_SECONDS.get(tf, 60)
        if bar_ts:
            elapsed = max(0.0, (datetime.now(UTC) - _aware(bar_ts)).total_seconds())
            next_bar_sec = int(step - (elapsed % step))
    return {
        "slot_id": str(slot.id),
        "symbol": slot.symbol,
        "timeframe": tf,
        "strategy_name": strategy.name if strategy else slot.symbol,
        "strategy_id": str(slot.strategy_id),
        "in_trade": slot.open_direction is not None,
        "direction": slot.open_direction,
        "quantity": slot.open_qty,
        "entry_price": _dec(slot.open_entry_price) if slot.open_entry_price is not None else None,
        "stop": _dec(slot.open_stop) if slot.open_stop is not None else None,
        "target": _dec(slot.open_target) if slot.open_target is not None else None,
        "state": state,
        "last_bar_ts": last_bar_ts,
        "cursor_bar_ts": slot.last_bar_ts.isoformat() if slot.last_bar_ts else None,
        "last_refresh_at": slot.last_refresh_at.isoformat() if slot.last_refresh_at else None,
        "last_error": slot.last_error,
        "last_open": last_print["open"] if last_print else None,
        "last_high": last_print["high"] if last_print else None,
        "last_low": last_print["low"] if last_print else None,
        "last_close": last_close,
        "last_volume": last_print["volume"] if last_print else None,
        "bar_age_sec": last_print["age_sec"] if last_print else None,
        "bars_in_dataset": last_print["row_count"] if last_print else 0,
        "feed_source": last_print["source"] if last_print else None,
        "next_bar_sec": next_bar_sec,
        "caught_up": caught_up,
        "armed": slot.last_bar_ts is None,
        "unrealized": _unrealized(slot, last_close, instrument.multiplier if instrument else None),
        "paper_trades": len(nets),
        "paper_net": _dec(sum(nets, Decimal(0))),
        "paper_win_rate_pct": round(100.0 * len(wins) / len(nets), 1) if nets else None,
        "baseline": baseline,
    }
