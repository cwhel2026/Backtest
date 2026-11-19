"""Run provider ingestion inside the Celery worker (sync DB session)."""

import uuid
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.instrument import Instrument
from app.models.market_data import HistoricalDataset
from app.models.research import ResearchJob
from app.services.market_data.bar_storage import persist_bars_to_dataset
from app.services.market_data.budget import record_actual_spend
from app.services.market_data.contract_series import selection_from_ingest_payload
from app.services.market_data.databento_client import (
    DEFAULT_CHUNK_DAYS,
    fetch_ohlcv_1m_chunked_to_store,
    quote_download_cost,
)
from app.services.market_data.dataset_catalog import (
    create_pending_dataset,
    finalize_dataset_after_write,
    ingest_fingerprint,
)
from app.services.market_data.derived_timeframes import derive_timeframes_from_1m_parent
from app.services.market_data.databento_ingest import bars_for_timeframe, fetch_databento_ohlcv_1m_with_meta
from app.services.market_data.validate_dataset import validate_and_persist
from app.services.market_data.finzdata_ingest import fetch_finzdata_ohlcv
from app.services.market_data.ibkr_ingest import bar_size_for_timeframe, fetch_ibkr_bars
from app.services.market_data.yahoo_ingest import bars_to_storage, fetch_yahoo_ohlcv


def parse_job_datetime(value: str | datetime) -> datetime:
    if isinstance(value, datetime):
        dt = value
    else:
        text = str(value).strip()
        if text.endswith("Z"):
            text = text.replace("Z", "+00:00")
        dt = datetime.fromisoformat(text)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt.astimezone(UTC)


def _job_progress(job_id: str | None, message: str, pct: int) -> None:
    if not job_id:
        return
    try:
        from app.db.session import SyncSessionLocal

        with SyncSessionLocal() as session:
            job = session.get(ResearchJob, uuid.UUID(job_id))
            if job:
                job.message = message
                job.progress_pct = min(99, max(1, pct))
                session.commit()
    except Exception:
        pass


def run_databento_ingestion(session: Session, payload: dict) -> HistoricalDataset:
    symbol = payload.get("instrument_symbol")
    store_tf = payload.get("timeframe", "1m")
    start = parse_job_datetime(payload["start"])
    end = parse_job_datetime(payload["end"])
    job_id = payload.get("research_job_id")

    inst = session.execute(select(Instrument).where(Instrument.symbol == symbol)).scalar_one_or_none()
    if not inst:
        raise ValueError(f"Unknown instrument {symbol}")

    series = selection_from_ingest_payload(payload, symbol)
    fingerprint = ingest_fingerprint(
        provider_slug="databento",
        instrument_symbol=symbol,
        timeframe="1m",
        start=start,
        end=end,
    )

    use_chunked = payload.get("chunked", True) and store_tf == "1m"

    if use_chunked:
        _job_progress(job_id, f"Downloading {symbol} 1m (chunked)", 15)
        dataset = create_pending_dataset(
            session,
            provider_slug="databento",
            instrument_id=inst.id,
            timeframe="1m",
            fingerprint=fingerprint,
            meta={
                "source": "databento_historical",
                "provider": "databento",
                "databento_dataset": "GLBX.MDP3",
                "databento_continuous_symbol": f"{symbol.strip().upper()}.c.0",
                "original_symbol": symbol.upper(),
                "requested_range": {"start": start.isoformat(), "end": end.isoformat()},
                "approved_cost_usd": payload.get("approved_cost_usd"),
                "cost_estimate_source": payload.get("cost_estimate_source"),
                "engine_version": "3.0",
                "chunked_ingest": True,
            },
        )
        session.flush()

        def on_chunk(info: dict) -> None:
            pct = 15 + int(55 * info["chunk"] / max(1, info["chunks_total"]))
            _job_progress(
                job_id,
                f"{symbol}: chunk {info['chunk']}/{info['chunks_total']} "
                f"({info['bars_total_written']:,} bars)",
                pct,
            )

        total_rows, sym_meta = fetch_ohlcv_1m_chunked_to_store(
            dataset.id,
            symbol,
            start,
            end,
            series=series,
            chunk_days=int(payload.get("chunk_days") or DEFAULT_CHUNK_DAYS),
            on_chunk=on_chunk,
        )
        if total_rows == 0:
            raise ValueError(
                f"No OHLCV bars returned for {symbol} ({start.isoformat()} → {end.isoformat()}). "
                "Verify Databento license includes GLBX.MDP3."
            )
        meta = dict(dataset.meta or {})
        meta.update(
            {
                **{k: v for k, v in sym_meta.items()},
                "bars_1m_downloaded": total_rows,
                "actual_contract_note": sym_meta.get("symbology_note"),
                "rollover_events": sym_meta.get("rollover_events", []),
            }
        )
        dataset.meta = meta
        finalize_dataset_after_write(session, dataset)
        _job_progress(job_id, f"Validating {symbol} 1m quality", 75)
        validate_and_persist(
            session,
            dataset,
            symbol=symbol,
            tick_size=inst.tick_size,
            instrument_trading_hours=inst.trading_hours or {},
        )
        qclass = (dataset.meta or {}).get("quality_class", "").lower()
        if qclass == "blocked":
            session.flush()
            return dataset

        if payload.get("derive_timeframes", True):
            _job_progress(job_id, f"Deriving 5m/15m/1h/4h for {symbol}", 85)
            derive_timeframes_from_1m_parent(
                session,
                parent=dataset,
                symbol=symbol,
                instrument_id=inst.id,
                range_start=start,
                range_end=end,
                tick_size=inst.tick_size,
                trading_hours=inst.trading_hours or {},
                parent_fingerprint=fingerprint,
            )
    else:
        bars_1m, sym_meta = fetch_databento_ohlcv_1m_with_meta(
            instrument_symbol=symbol, start=start, end=end, series=series
        )
        if not bars_1m:
            raise ValueError(f"No OHLCV bars for {symbol}")
        stored = bars_for_timeframe(bars_1m, store_tf)
        from app.services.market_data.dataset_catalog import create_versioned_dataset

        db_symbol = f"{symbol.strip().upper()}.c.0"
        dataset = create_versioned_dataset(
            session,
            provider_slug="databento",
            instrument_id=inst.id,
            timeframe=store_tf,
            bars=stored,
            fingerprint=ingest_fingerprint(
                provider_slug="databento",
                instrument_symbol=symbol,
                timeframe=store_tf,
                start=start,
                end=end,
            ),
            meta={
                "source": "databento_historical",
                "provider": "databento",
                "databento_dataset": "GLBX.MDP3",
                "databento_continuous_symbol": db_symbol,
                "original_symbol": symbol.upper(),
                "actual_contract_note": sym_meta.get("symbology_note"),
                "rollover_events": sym_meta.get("rollover_events", []),
                "requested_range": {"start": start.isoformat(), "end": end.isoformat()},
                "bars_1m_downloaded": len(bars_1m),
                "approved_cost_usd": payload.get("approved_cost_usd"),
                "cost_estimate_source": payload.get("cost_estimate_source"),
                "engine_version": "3.0",
                **{k: v for k, v in sym_meta.items() if k not in ("rollover_events", "symbology_note")},
            },
        )
        validate_and_persist(
            session,
            dataset,
            symbol=symbol,
            tick_size=inst.tick_size,
            instrument_trading_hours=inst.trading_hours or {},
        )

    actual_usd = float(payload.get("approved_cost_usd") or 0)
    try:
        quote = quote_download_cost(symbol, start, end)
        if not actual_usd:
            actual_usd = quote.usd
    except ValueError:
        pass
    if actual_usd > 0:
        record_actual_spend(session, actual_usd)

    session.flush()
    return dataset


def run_finzdata_ingestion(session: Session, payload: dict) -> HistoricalDataset:
    symbol = payload.get("instrument_symbol")
    timeframe = payload.get("timeframe", "5m")
    start = parse_job_datetime(payload["start"])
    end = parse_job_datetime(payload["end"])

    inst = session.execute(select(Instrument).where(Instrument.symbol == symbol)).scalar_one_or_none()
    if not inst:
        raise ValueError(f"Unknown instrument {symbol}")

    bars, root, download_tf = fetch_finzdata_ohlcv(
        instrument_symbol=symbol,
        start=start,
        end=end,
        target_timeframe=timeframe,
    )
    if not bars:
        raise ValueError(
            f"No FinzData bars for {root} {timeframe} ({start.isoformat()} → {end.isoformat()})."
        )
    stored = bars_to_storage(bars, source_timeframe=download_tf, target_timeframe=timeframe)
    return persist_bars_to_dataset(
        session,
        provider_slug="finzdata",
        instrument_id=inst.id,
        timeframe=timeframe,
        bars=stored,
        meta={
            "source": "finzdata_historical",
            "finzdata_root": root,
            "continuous": True,
            "requested_range": {"start": start.isoformat(), "end": end.isoformat()},
            "bars_downloaded": len(bars),
        },
    )


def run_ibkr_ingestion(session: Session, payload: dict) -> HistoricalDataset:
    symbol = payload.get("instrument_symbol")
    timeframe = payload.get("timeframe", "5m")
    start = parse_job_datetime(payload["start"])
    end = parse_job_datetime(payload["end"])

    inst = session.execute(select(Instrument).where(Instrument.symbol == symbol)).scalar_one_or_none()
    if not inst:
        raise ValueError(f"Unknown instrument {symbol}")

    bars = fetch_ibkr_bars(
        symbol,
        start=start,
        end=end,
        bar_size=bar_size_for_timeframe(timeframe),
    )
    stored = bars_to_storage(bars, source_timeframe=timeframe, target_timeframe=timeframe)
    return persist_bars_to_dataset(
        session,
        provider_slug="ibkr",
        instrument_id=inst.id,
        timeframe=timeframe,
        bars=stored,
        meta={
            "source": "ibkr_gateway",
            "requested_range": {"start": start.isoformat(), "end": end.isoformat()},
        },
    )


def run_yahoo_ingestion(session: Session, payload: dict) -> HistoricalDataset:
    symbol = payload.get("instrument_symbol")
    timeframe = payload.get("timeframe", "5m")
    start = parse_job_datetime(payload["start"])
    end = parse_job_datetime(payload["end"])

    inst = session.execute(select(Instrument).where(Instrument.symbol == symbol)).scalar_one_or_none()
    if not inst:
        raise ValueError(f"Unknown instrument {symbol}")

    bars, yahoo_ticker, download_tf = fetch_yahoo_ohlcv(
        instrument_symbol=symbol,
        start=start,
        end=end,
        target_timeframe=timeframe,
    )
    if not bars:
        raise ValueError(
            f"No Yahoo Finance bars for {yahoo_ticker} ({start.isoformat()} → {end.isoformat()}). "
            "Check symbol or try a shorter range."
        )

    stored = bars_to_storage(bars, source_timeframe=download_tf, target_timeframe=timeframe)

    return persist_bars_to_dataset(
        session,
        provider_slug="yahoo",
        instrument_id=inst.id,
        timeframe=timeframe,
        bars=stored,
        meta={
            "source": "yahoo_finance",
            "yahoo_ticker": yahoo_ticker,
            "continuous": True,
            "research_warning": "Delayed unlicensed feed — not genuine for prop research.",
            "requested_range": {"start": start.isoformat(), "end": end.isoformat()},
        },
    )