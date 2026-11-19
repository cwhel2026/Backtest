"""Quality validation, READY/WARNING/BLOCKED classification, video strategy readiness."""

from __future__ import annotations

from collections.abc import Sequence
from decimal import Decimal

from sqlalchemy.orm import Session

from app.backtest.bars import Bar, load_bars
from app.services.market_data.contract_series import detect_rollover_jumps
from app.services.market_data.exchange_calendar import SessionPolicy, expected_closure_between, session_policy_from_spec
from app.services.market_data.sessions import session_keys_for_bars
from app.models.enums import DatasetValidationStatus
from app.models.market_data import DataQualityReport, HistoricalDataset
from app.services.market_data.data_lineage import apply_lineage_meta, assert_genuine_for_backtest
from app.services.market_data.quality import DatasetQualityReport, audit_bars

QualityClass = str  # ready | warning | blocked


def classify_quality(report: DatasetQualityReport, *, symbol: str, timeframe: str) -> tuple[QualityClass, list[str]]:
    issues: list[str] = []
    if report.bar_count == 0:
        return "blocked", ["empty dataset"]
    if report.duplicates > 0 or report.ordering_errors > 0 or report.malformed_bars > 0:
        return "blocked", list(report.warnings) + ["hard quality failures"]
    if report.bar_count < 500 and timeframe in ("5m", "15m", "30m", "1h"):
        issues.append("low bar count for strategy research")
    if len(report.gaps) > 40:
        issues.append("many time gaps")
    if issues:
        return "warning", issues + report.warnings
    if report.warnings:
        return "warning", report.warnings
    return "ready", []


def extended_audit(
    bars: Sequence[Bar],
    *,
    timeframe: str,
    symbol: str,
    tick_size: Decimal | None = None,
    rollover_events: list[dict] | None = None,
    instrument_trading_hours: dict | None = None,
) -> DatasetQualityReport:
    base = audit_bars(bars, timeframe=timeframe, source=None)
    warnings = list(base.warnings)
    malformed = base.malformed_bars
    policy = session_policy_from_spec({"session": {"allowed": ["RTH", "ETH"]}}, instrument_trading_hours)

    gaps: list[dict] = []
    for g in base.gaps:
        try:
            prev = datetime.fromisoformat(g["from"].replace("Z", "+00:00"))
            curr = datetime.fromisoformat(g["to"].replace("Z", "+00:00"))
        except Exception:
            gaps.append(g)
            continue
        if expected_closure_between(prev, curr, policy):
            continue
        gaps.append(g)

    roll_hits = detect_rollover_jumps(list(bars), rollover_events or [], tick_size=tick_size or Decimal("0.25"))
    if roll_hits:
        warnings.append(f"{len(roll_hits)} unadjusted roll-style gaps (documented, not stitched)")
    return DatasetQualityReport(
        bar_count=base.bar_count,
        duplicates=base.duplicates,
        ordering_errors=base.ordering_errors,
        malformed_bars=malformed,
        gaps=gaps,
        warnings=warnings,
        coverage_start=base.coverage_start,
        coverage_end=base.coverage_end,
        source=base.source,
    )


def video_strategy_readiness(
    bars: Sequence[Bar],
    *,
    symbol: str,
    timeframe: str,
    instrument_trading_hours: dict | None = None,
) -> dict:
    """Warm-up checks for video_liquidity_sweep and video_anchor_bos — no rule changes."""
    if not bars:
        return {
            "video_liquidity_sweep": {"ready": False, "reason": "no bars"},
            "video_anchor_bos": {"ready": False, "reason": "no bars"},
        }
    spec = {"session": {"allowed": ["RTH"], "timezone": "America/Chicago"}}
    session_keys = session_keys_for_bars(list(bars), spec, instrument_trading_hours=instrument_trading_hours)
    sessions = {k for k in session_keys if k.startswith("rth:")}
    coverage_days = len(sessions)
    mins = {"1m": 1, "5m": 5, "15m": 15, "30m": 30, "1h": 60}.get(timeframe, 5)
    bars_per_session = max(1, (6 * 60 + 30) // mins)
    pivot_warmup = 12  # conservative for 3+3 pivots + session history

    sweep_ready = coverage_days >= 2 and len(bars) >= bars_per_session * 2 + pivot_warmup
    sweep_reason = (
        "ok"
        if sweep_ready
        else f"need ≥2 completed sessions (have {coverage_days}) and ~{bars_per_session * 2 + pivot_warmup} bars"
    )
    anchor_ready = len(bars) >= pivot_warmup * 3
    anchor_reason = "ok" if anchor_ready else f"need ~{pivot_warmup * 3} bars for pivot confirmation"
    return {
        "video_liquidity_sweep": {"ready": sweep_ready, "reason": sweep_reason, "session_days": coverage_days},
        "video_anchor_bos": {"ready": anchor_ready, "reason": anchor_reason, "bar_count": len(bars)},
        "symbol": symbol,
        "timeframe": timeframe,
    }


def backtest_zero_trade_hint(
    trade_count: int,
    readiness: dict,
    quality_class: str,
) -> str | None:
    if trade_count > 0:
        return None
    if quality_class == "blocked":
        return "execution_blocked: dataset quality is BLOCKED"
    ls = readiness.get("video_liquidity_sweep", {})
    ab = readiness.get("video_anchor_bos", {})
    if not ls.get("ready") and not ab.get("ready"):
        return f"insufficient_warmup: sweep({ls.get('reason')}); anchor({ab.get('reason')})"
    return "valid_no_signals: data adequate but strategy found no qualifying setups in range"


def validate_and_persist(
    session: Session,
    dataset: HistoricalDataset,
    *,
    symbol: str,
    tick_size: Decimal | None,
    instrument_trading_hours: dict | None = None,
) -> dict:
    bars = load_bars(session, dataset.id)
    rollover_events = (dataset.meta or {}).get("rollover_events") if isinstance(dataset.meta, dict) else []
    th = instrument_trading_hours if instrument_trading_hours is not None else {}
    report = extended_audit(
        bars,
        timeframe=dataset.timeframe,
        symbol=symbol,
        tick_size=tick_size,
        rollover_events=rollover_events,
        instrument_trading_hours=th,
    )
    qclass, notes = classify_quality(report, symbol=symbol, timeframe=dataset.timeframe)
    readiness = video_strategy_readiness(
        bars, symbol=symbol, timeframe=dataset.timeframe, instrument_trading_hours=th
    )

    gap_max = 0
    for g in report.gaps:
        gap_max = max(gap_max, int(g.get("missing_minutes", 0)))

    dq = DataQualityReport(
        dataset_id=dataset.id,
        duplicate_bars=report.duplicates,
        missing_bars=sum(int(g.get("missing_minutes", 0)) for g in report.gaps),
        gap_seconds_max=gap_max * 60 if gap_max else None,
        notes="; ".join(notes + report.warnings)[:4000],
        details={
            "quality_class": qclass,
            "report": report.to_dict(),
            "video_readiness": readiness,
        },
    )
    session.add(dq)
    session.flush()

    meta = dict(dataset.meta or {})
    meta["quality_class"] = qclass
    meta["video_readiness"] = readiness
    meta["quality_report_id"] = str(dq.id)
    provider_slug = meta.get("provider") or meta.get("source") or "unknown"
    if isinstance(provider_slug, str) and provider_slug.startswith("databento"):
        provider_slug = "databento"
    meta = apply_lineage_meta(meta, provider_slug=str(provider_slug))
    dataset.meta = meta
    dataset.quality_score = Decimal("100") if qclass == "ready" else Decimal("70") if qclass == "warning" else Decimal("0")
    if qclass == "blocked":
        dataset.validation_status = DatasetValidationStatus.FAILED
    else:
        dataset.validation_status = DatasetValidationStatus.VALIDATED
    session.flush()
    return {
        "quality_class": qclass,
        "validation_status": dataset.validation_status.value,
        "report": report.to_dict(),
        "video_readiness": readiness,
        "notes": notes,
    }