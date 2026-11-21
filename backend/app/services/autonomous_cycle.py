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
from app.services.market_data.dataset_gc import reclaim_search_disk
from app.services.market_data.ingestion_runner import run_yahoo_ingestion
from app.services.market_data.ohlcv_cache import ensure_search_dataset, latest_dataset
from app.services.search_heartbeat import SearchJobHeartbeat
from app.services.search_progress import entry_family_label, initial_search_progress, merge_search_progress
from app.services.strategy_search import persist_search_hits, run_deep_search
from app.util.db_errors import compact_error, is_disk_full, set_job_message

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


def _aware(value: datetime) -> datetime:
    return value if value.tzinfo else value.replace(tzinfo=UTC)


def job_heartbeat(job: ResearchJob) -> datetime | None:
    raw = (job.payload or {}).get("heartbeat")
    if not isinstance(raw, str) or not raw:
        return None
    try:
        return _aware(datetime.fromisoformat(raw))
    except ValueError:
        return None


def job_is_stale(job: ResearchJob, now: datetime | None = None) -> bool:
    """Queued too long without the worker, or running with no recent heartbeat (dead worker)."""
    settings = get_settings()
    queued_min = int(getattr(settings, "search_stale_queued_minutes", 12) or 12)
    running_min = int(getattr(settings, "search_stale_running_minutes", 25) or 25)
    now = now or datetime.now(UTC)
    created = _aware(job.created_at)
    if job.status == ResearchJobStatus.QUEUED and now - created > timedelta(minutes=queued_min):
        return True
    if job.status != ResearchJobStatus.RUNNING:
        return False
    beat = job_heartbeat(job) or _aware(job.started_at or created)
    return now - beat > timedelta(minutes=running_min)


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


def _latest_dataset(session: Session, symbol: str, timeframe: str = "5m") -> HistoricalDataset | None:
    return latest_dataset(session, symbol, timeframe)


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
        prior = job.payload or {}
        sp = prior.get("search_progress") or {}
        if prior.get("bounded_run"):
            budget = int(sp.get("budget_per_symbol") or prior.get("budget_per_symbol") or budget)
            history_days = int(sp.get("history_days") or prior.get("history_days") or history_days)
        job.status = ResearchJobStatus.RUNNING
        set_job_message(job, "Loading market data")
        job.started_at = datetime.now(UTC)
        progress = initial_search_progress(symbols=symbols, budget=budget, history_days=history_days)
        if prior.get("bounded_run"):
            progress = {**progress, **sp, "budget_per_symbol": budget, "history_days": history_days, "phase": "starting"}
        job.payload = {**prior, "actor": actor, "budget_per_symbol": budget, "search_progress": progress}
        session.flush()
    else:
        job = ResearchJob(
            kind=ResearchJobKind.VALIDATION,
            status=ResearchJobStatus.RUNNING,
            title=PROP_SEARCH_JOB_TITLE,
            message="Loading market data",
            started_at=datetime.now(UTC),
            payload={
                "actor": actor,
                "budget_per_symbol": budget,
                "search_progress": initial_search_progress(
                    symbols=symbols, budget=budget, history_days=history_days
                ),
            },
        )
        session.add(job)
        session.flush()

    job_pk = job.id
    session.commit()
    try:
        reclaim_search_disk(session)
        session.commit()
    except Exception:
        session.rollback()

    def _job() -> ResearchJob:
        current = session.get(ResearchJob, job_pk)
        if current is None:
            raise RuntimeError("Search job disappeared")
        return current

    heartbeat = SearchJobHeartbeat(job_pk)
    heartbeat.start()
    try:
        timeframes = settings.search_timeframe_list()
        datasets: dict[tuple[str, str], HistoricalDataset] = {}
        warnings: list[str] = []
        for idx, symbol in enumerate(symbols):
            for tf in timeframes:
                days = int(settings.search_1m_window_days()) if tf == "1m" else history_days
                job = _job()
                merge_search_progress(
                    job,
                    phase="loading_data",
                    current_symbol=symbol,
                    symbol_index=idx,
                )
                key = (symbol, tf)
                stored = _latest_dataset(session, symbol, tf)
                if stored and int(stored.row_count or 0) >= 80:
                    set_job_message(job, f"Using stored {symbol} {tf} ({stored.row_count} bars)")
                else:
                    set_job_message(job, f"Downloading {symbol} {tf} ({days} days) — stored for later searches")
                session.commit()
                try:
                    with session.begin_nested():
                        ds, provider_label = ensure_search_dataset(session, symbol, tf, days)
                    session.commit()
                    datasets[key] = ds
                    summary.setdefault("symbols", {}).setdefault(symbol, {})[tf] = {
                        "dataset_id": str(ds.id),
                        "row_count": ds.row_count,
                        "provider": provider_label,
                    }
                except Exception as exc:
                    session.rollback()
                    note = compact_error(exc)
                    if is_disk_full(exc):
                        try:
                            reclaim_search_disk(session)
                            session.commit()
                            cached = _latest_dataset(session, symbol, tf)
                            if cached:
                                datasets[key] = cached
                                summary.setdefault("symbols", {}).setdefault(symbol, {})[tf] = {
                                    "dataset_id": str(cached.id),
                                    "row_count": cached.row_count,
                                    "provider": f"stored after disk full {tf}",
                                    "warning": note,
                                }
                            else:
                                with session.begin_nested():
                                    ds, provider_label = ensure_search_dataset(session, symbol, tf, days)
                                session.commit()
                                datasets[key] = ds
                                summary.setdefault("symbols", {}).setdefault(symbol, {})[tf] = {
                                    "dataset_id": str(ds.id),
                                    "row_count": ds.row_count,
                                    "provider": provider_label,
                                }
                        except Exception as retry_exc:
                            session.rollback()
                            note = compact_error(retry_exc)
                    if key not in datasets:
                        warnings.append(f"{symbol} {tf}: {note}")
                        ds = _latest_dataset(session, symbol, tf)
                        if ds:
                            datasets[key] = ds
                            summary.setdefault("symbols", {}).setdefault(symbol, {})[tf] = {
                                "dataset_id": str(ds.id),
                                "row_count": ds.row_count,
                                "warning": note,
                            }
                job = _job()
                loaded = list((job.payload or {}).get("search_progress", {}).get("markets_loaded") or [])
                if key in datasets:
                    row_count = summary["symbols"].get(symbol, {}).get(tf, {}).get("row_count")
                    loaded.append(f"{symbol} {tf} ({row_count} bars)" if row_count is not None else f"{symbol} {tf}")
                merge_search_progress(job, markets_loaded=loaded)
                warn_bit = ""
                if warnings and warnings[-1].startswith(f"{symbol} {tf}"):
                    warn_bit = f" — {compact_error(warnings[-1])}"
                label = summary.get("symbols", {}).get(symbol, {}).get(tf, {}).get("provider")
                loaded_bit = f" · {label}" if label else ""
                set_job_message(job, f"Loaded {symbol} {tf}{loaded_bit}{warn_bit}")
                session.commit()

        job = _job()
        merge_search_progress(job, phase="scoring", current_symbol=None)
        ai_bit = " + AI mutation rounds" if get_settings().ai_configured else ""
        set_job_message(job, f"Scoring {len(symbols)} symbols × {timeframes} TFs ({budget} 5m combos{ai_bit})")
        session.commit()

        all_winners: list[str] = []
        total_eval = 0
        finished_symbols: list[str] = []
        search_slots = [(s, tf) for s in symbols for tf in timeframes]
        for slot_idx, (symbol, tf) in enumerate(search_slots):
            ds = datasets.get((symbol, tf)) or _latest_dataset(session, symbol, tf)
            if not ds:
                continue
            from app.services.market_data.dataset_research import prepare_dataset_for_research

            elig = prepare_dataset_for_research(session, ds)
            if not elig.ok:
                warnings.append(f"{symbol} {tf}: skipped research — {elig.reason}")
                job = _job()
                set_job_message(job, f"Skipped {symbol} {tf}: {elig.reason}")
                session.commit()
                continue
            inst = session.get(Instrument, ds.instrument_id)
            if not inst:
                continue
            sym_idx = list(symbols).index(symbol)
            tf_budget = int(settings.search_1m_budget_per_symbol) if tf == "1m" else budget

            def _pulse(
                done: int,
                *,
                spec: dict | None = None,
                subphase: str = "walk_forward",
                symbol: str = symbol,
                tf: str = tf,
                tf_budget: int = tf_budget,
            ) -> None:
                current = _job()
                setup_name = (spec or {}).get("name") if spec else None
                combo_est = min(tf_budget, max(0, done // 2))
                merge_search_progress(
                    current,
                    phase="scoring",
                    current_symbol=f"{symbol} {tf}",
                    symbol_index=sym_idx,
                    tests_completed=done,
                    tests_target_estimate=tf_budget * 4,
                    combos_per_symbol=tf_budget,
                    combos_completed=combo_est,
                    current_setup=setup_name,
                    setup_family=entry_family_label(spec),
                    scoring_subphase=subphase,
                    winners_saved=len(all_winners),
                    symbols_finished=list(finished_symbols),
                )
                bit = f" · {setup_name}" if setup_name else ""
                fam = entry_family_label(spec)
                fam_bit = f" [{fam}]" if fam else ""
                phase_bit = subphase.replace("_", " ")
                msg = (
                    f"Scoring {symbol} {tf}{fam_bit} · combo ~{combo_est}/{tf_budget} · "
                    f"{done} backtests · {phase_bit}{bit}"
                )
                set_job_message(current, msg)
                symbol_fraction = combo_est / max(tf_budget, 1)
                overall = (slot_idx + symbol_fraction) / max(len(search_slots), 1)
                current.progress_pct = min(94, int(100 * overall))
                heartbeat.snapshot = {
                    "phase": "scoring",
                    "current_symbol": f"{symbol} {tf}",
                    "symbol_index": sym_idx,
                    "tests_completed": done,
                    "combos_completed": combo_est,
                    "combos_per_symbol": tf_budget,
                    "current_setup": setup_name,
                    "setup_family": entry_family_label(spec),
                    "scoring_subphase": subphase,
                    "message": msg,
                }
                session.commit()

            _pulse(0, subphase="start")
            hits, evaluated, search_stats = run_deep_search(
                session,
                symbol=symbol,
                dataset=ds,
                instrument=inst,
                budget=tf_budget,
                seed=seed + hash(f"{symbol}{tf}") % 1000,
                on_progress=_pulse,
            )
            total_eval += evaluated
            job = _job()
            merge_search_progress(
                job,
                experiments_recorded=search_stats.get("trials_recorded", 0),
                ai_round=search_stats.get("ai_rounds", 0),
            )
            session.commit()
            job = _job()
            merge_search_progress(job, phase="saving", current_symbol=symbol, scoring_subphase="persist")
            set_job_message(job, f"Saving {symbol} keepers ({len(hits)} hits to backtest)")
            session.commit()
            winners = persist_search_hits(
                session,
                hits,
                ds,
                symbol,
                actor=actor,
                forward_sim=settings.autonomous_forward_sim,
            )
            all_winners.extend(winners)
            summary["backtests"].extend([{"name": w, "symbol": symbol, "timeframe": tf} for w in winners])
            finished_symbols.append(f"{symbol}:{tf}")
            job = _job()
            merge_search_progress(
                job,
                winners_saved=len(all_winners),
                symbols_finished=list(finished_symbols),
                tests_completed=total_eval,
            )
            set_job_message(job, f"Finished {symbol} {tf}: {len(winners)} saved · {total_eval} tests so far")
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
            set_job_message(job, f"Found {len(all_winners)} walk-forward winners")
            reverse_n = sum(1 for w in all_winners if w.startswith("REV "))
            detail = (
                f"Scored {total_eval}+ backtests · {len(all_winners)} passed OOS"
                f"{f' ({reverse_n} reverse fades)' if reverse_n else ''}: "
                f"{', '.join(all_winners[:6])}"
            )
        else:
            set_job_message(job, "No walk-forward winners this cycle")
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
        heartbeat.stop()
        return summary
    except Exception as exc:
        session.rollback()
        heartbeat.stop()
        try:
            reclaim_search_disk(session)
            session.commit()
        except Exception:
            session.rollback()
        job = session.get(ResearchJob, job_pk)
        if job:
            try:
                job.status = ResearchJobStatus.FAILED
                job.error = compact_error(exc)
                set_job_message(job, compact_error(exc))
                job.completed_at = datetime.now(UTC)
                session.add(
                    ResearchActivity(
                        headline="Deep search failed",
                        detail=compact_error(exc, limit=400),
                        job_id=job.id,
                    )
                )
                session.commit()
            except Exception:
                session.rollback()
        raise