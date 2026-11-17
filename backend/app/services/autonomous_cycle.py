"""Autonomous prop-firm research — deep combinatorial search + walk-forward validation."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from sqlalchemy import desc, select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.models.enums import ResearchJobKind, ResearchJobStatus
from app.models.market_data import HistoricalDataset
from app.models.instrument import Instrument
from app.models.research import ResearchActivity, ResearchJob
from app.services.market_data.ingestion_runner import run_yahoo_ingestion
from app.services.strategy_search import persist_search_hits, run_deep_search

# Nasdaq micro + e-mini always included (even if SEARCH_SYMBOLS omits them).
NASDAQ_SYMBOLS = ("MNQ", "NQ")
DEFAULT_SEARCH_SYMBOLS = ("MNQ", "NQ", "MES", "ES")
PROP_SEARCH_JOB_TITLE = "Deep prop search"


def resolve_search_symbols() -> tuple[str, ...]:
    settings = get_settings()
    raw = getattr(settings, "search_symbols", None) or ",".join(DEFAULT_SEARCH_SYMBOLS)
    ordered: list[str] = []
    seen: set[str] = set()
    for token in raw.split(","):
        sym = token.strip().upper()
        if sym and sym not in seen:
            seen.add(sym)
            ordered.append(sym)
    for sym in NASDAQ_SYMBOLS:
        if sym not in seen:
            ordered.insert(0, sym)
            seen.add(sym)
    return tuple(ordered)


def _search_symbols() -> tuple[str, ...]:
    return resolve_search_symbols()


def _ingest_yahoo(session: Session, symbol: str, days: int) -> HistoricalDataset:
    end = datetime.now(UTC)
    start = end - timedelta(days=days)
    payload = {
        "provider": "yahoo",
        "instrument_symbol": symbol,
        "timeframe": "5m",
        "start": start.isoformat(),
        "end": end.isoformat(),
    }
    return run_yahoo_ingestion(session, payload)


def job_is_stale(job: ResearchJob, now: datetime | None = None) -> bool:
    """Queued with no worker, or running long enough that the process was killed."""
    now = now or datetime.now(UTC)
    created = job.created_at if job.created_at.tzinfo else job.created_at.replace(tzinfo=UTC)
    if job.status == ResearchJobStatus.QUEUED and now - created > timedelta(minutes=3):
        return True
    started = job.started_at or created
    if started.tzinfo is None:
        started = started.replace(tzinfo=UTC)
    return job.status == ResearchJobStatus.RUNNING and now - started > timedelta(minutes=40)


def find_active_prop_search_job(session: Session) -> ResearchJob | None:
    return session.execute(
        select(ResearchJob)
        .where(
            ResearchJob.title == PROP_SEARCH_JOB_TITLE,
            ResearchJob.status.in_((ResearchJobStatus.QUEUED, ResearchJobStatus.RUNNING)),
        )
        .order_by(desc(ResearchJob.created_at))
        .limit(1)
    ).scalar_one_or_none()


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


def run_autonomous_prop_cycle(
    session: Session,
    actor: str = "autopilot",
    job_id: str | None = None,
) -> dict:
    settings = get_settings()
    budget = int(getattr(settings, "search_budget_per_symbol", 120) or 120)
    history_days = int(getattr(settings, "search_history_days", 35) or 35)
    symbols = _search_symbols()
    seed = int(datetime.now(UTC).strftime("%Y%m%d%H"))

    summary: dict = {"symbols": {}, "backtests": [], "sims": [], "search_evaluations": 0}

    if job_id:
        from uuid import UUID

        job = session.get(ResearchJob, UUID(job_id) if isinstance(job_id, str) else job_id)
        if not job:
            raise ValueError(f"Unknown prop search job {job_id}")
        job.status = ResearchJobStatus.RUNNING
        job.message = "Loading market data"
        job.started_at = datetime.now(UTC)
        job.payload = {**(job.payload or {}), "actor": actor, "budget_per_symbol": budget}
        session.flush()
    else:
        job = ResearchJob(
            kind=ResearchJobKind.VALIDATION,
            status=ResearchJobStatus.RUNNING,
            title=PROP_SEARCH_JOB_TITLE,
            message="Loading market data",
            started_at=datetime.now(UTC),
            payload={"actor": actor, "budget_per_symbol": budget},
        )
        session.add(job)
        session.flush()

    job_pk = job.id
    session.commit()

    def _job() -> ResearchJob:
        current = session.get(ResearchJob, job_pk)
        if current is None:
            raise RuntimeError("Search job disappeared")
        return current

    try:
        datasets: dict[str, HistoricalDataset] = {}
        warnings: list[str] = []
        for symbol in symbols:
            try:
                with session.begin_nested():
                    ds = _ingest_yahoo(session, symbol, history_days)
                session.commit()
                datasets[symbol] = ds
                summary["symbols"][symbol] = {"dataset_id": str(ds.id), "row_count": ds.row_count}
            except Exception as exc:
                session.rollback()
                warnings.append(f"{symbol}: {exc}")
                ds = _latest_dataset(session, symbol)
                if ds:
                    datasets[symbol] = ds
                    summary["symbols"][symbol] = {
                        "dataset_id": str(ds.id),
                        "row_count": ds.row_count,
                        "warning": str(exc),
                    }
            job = _job()
            job.message = f"Loaded {symbol}" + (f" — {warnings[-1]}" if warnings else "")
            session.commit()

        job = _job()
        job.message = f"Scoring {len(datasets)} markets ({budget} tests each)"
        session.commit()

        all_winners: list[str] = []
        total_eval = 0
        for symbol in symbols:
            ds = datasets.get(symbol)
            if not ds:
                continue
            inst = session.get(Instrument, ds.instrument_id)
            if not inst:
                continue
            hits, evaluated = run_deep_search(
                session,
                symbol=symbol,
                dataset=ds,
                instrument=inst,
                budget=budget,
                seed=seed + hash(symbol) % 1000,
            )
            total_eval += evaluated
            winners = persist_search_hits(
                session,
                hits,
                ds,
                symbol,
                actor=actor,
                forward_sim=settings.autonomous_forward_sim,
            )
            all_winners.extend(winners)
            summary["backtests"].extend([{"name": w, "symbol": symbol} for w in winners])
            job = _job()
            job.message = f"Finished {symbol}: {len(winners)} saved · {total_eval} tests so far"
            job.progress_pct = min(95, int(100 * (list(symbols).index(symbol) + 1) / max(len(symbols), 1)))
            session.add(
                ResearchActivity(
                    headline=f"Searched {symbol}",
                    detail=job.message,
                    job_id=job.id,
                )
            )
            session.commit()

        summary["search_evaluations"] = total_eval
        try:
            from app.services.paper_book import tick_paper_book

            summary["paper"] = tick_paper_book(session)
        except Exception as exc:
            session.rollback()
            summary["paper"] = {"error": str(exc)}
        job = _job()
        job.status = ResearchJobStatus.COMPLETED
        job.progress_pct = 100
        job.completed_at = datetime.now(UTC)
        if all_winners:
            job.message = f"Found {len(all_winners)} walk-forward winners"
            reverse_n = sum(1 for w in all_winners if w.startswith("REV "))
            detail = (
                f"Scored {total_eval}+ backtests · {len(all_winners)} passed OOS"
                f"{f' ({reverse_n} reverse fades)' if reverse_n else ''}: "
                f"{', '.join(all_winners[:6])}"
            )
        else:
            job.message = "No walk-forward winners this cycle"
            detail = f"Scored {total_eval} tests — none passed the prop screen."
            if warnings:
                detail += " Data notes: " + "; ".join(warnings[:3])
            elif total_eval == 0:
                detail += " No bars were available to test. Check that Yahoo data can download."

        session.add(
            ResearchActivity(
                headline="Deep search finished",
                detail=detail,
                job_id=job.id,
                meta={**summary, "winners": all_winners},
            )
        )
        job.payload = {**job.payload, "summary": summary}
        session.commit()
        return summary
    except Exception as exc:
        session.rollback()
        job = session.get(ResearchJob, job_pk)
        if job:
            job.status = ResearchJobStatus.FAILED
            job.error = str(exc)
            job.completed_at = datetime.now(UTC)
            session.add(
                ResearchActivity(headline="Deep search failed", detail=str(exc), job_id=job.id)
            )
            session.commit()
        raise