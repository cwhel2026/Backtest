"""Append-only forward-test ledger with idempotent writes."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.live_lab import ForwardTestLedgerEvent


def append_ledger_event(
    session: Session,
    *,
    run_id: UUID | None,
    event_type: str,
    idempotency_key: str,
    payload: dict,
    exchange_ts: datetime | None,
    server_received_ts: datetime | None = None,
    decision_ts: datetime | None = None,
) -> ForwardTestLedgerEvent | None:
    existing = session.execute(
        select(ForwardTestLedgerEvent).where(
            ForwardTestLedgerEvent.run_id == run_id,
            ForwardTestLedgerEvent.idempotency_key == idempotency_key,
        )
    ).scalar_one_or_none()
    if existing:
        return None
    seq = session.execute(
        select(func.coalesce(func.max(ForwardTestLedgerEvent.sequence), 0)).where(
            ForwardTestLedgerEvent.run_id == run_id
        )
    ).scalar_one()
    row = ForwardTestLedgerEvent(
        run_id=run_id,
        event_type=event_type,
        idempotency_key=idempotency_key,
        payload=payload,
        exchange_ts=exchange_ts,
        server_received_ts=server_received_ts or datetime.now(UTC),
        decision_ts=decision_ts,
        sequence=int(seq) + 1,
    )
    session.add(row)
    return row


def list_ledger_events(session: Session, run_id: UUID, limit: int = 200) -> list[ForwardTestLedgerEvent]:
    return (
        session.execute(
            select(ForwardTestLedgerEvent)
            .where(ForwardTestLedgerEvent.run_id == run_id)
            .order_by(ForwardTestLedgerEvent.sequence.desc())
            .limit(limit)
        )
        .scalars()
        .all()
    )