"""Dataset quality audit — duplicates, gaps, OHLC sanity (no fabricated fills)."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal

from app.backtest.bars import Bar


@dataclass
class DatasetQualityReport:
    bar_count: int
    duplicates: int
    ordering_errors: int
    malformed_bars: int
    gaps: list[dict]
    warnings: list[str]
    coverage_start: datetime | None
    coverage_end: datetime | None
    source: str | None = None

    def to_dict(self) -> dict:
        return {
            "bar_count": self.bar_count,
            "duplicates": self.duplicates,
            "ordering_errors": self.ordering_errors,
            "malformed_bars": self.malformed_bars,
            "gaps": self.gaps,
            "warnings": self.warnings,
            "coverage_start": self.coverage_start.isoformat() if self.coverage_start else None,
            "coverage_end": self.coverage_end.isoformat() if self.coverage_end else None,
            "source": self.source,
        }


def expected_step_minutes(timeframe: str) -> int:
    mapping = {"1m": 1, "5m": 5, "15m": 15, "1h": 60, "1d": 1440}
    return mapping.get(timeframe, 5)


def audit_bars(
    bars: Sequence[Bar],
    *,
    timeframe: str,
    source: str | None = None,
    max_gap_report: int = 25,
) -> DatasetQualityReport:
    if not bars:
        return DatasetQualityReport(
            0,
            0,
            0,
            0,
            [],
            ["empty dataset"],
            None,
            None,
            source,
        )
    step = timedelta(minutes=expected_step_minutes(timeframe))
    duplicates = 0
    ordering = 0
    malformed = 0
    gaps: list[dict] = []
    warnings: list[str] = []
    seen: set[datetime] = set()
    prev = bars[0].ts
    for i, b in enumerate(bars):
        if b.ts in seen:
            duplicates += 1
        seen.add(b.ts)
        if i and b.ts < prev:
            ordering += 1
        if b.high < b.low or b.open < b.low or b.open > b.high or b.close < b.low or b.close > b.high:
            malformed += 1
        if i and b.ts - prev > step * 2:
            gaps.append(
                {
                    "from": prev.isoformat(),
                    "to": b.ts.isoformat(),
                    "missing_minutes": int((b.ts - prev).total_seconds() // 60),
                }
            )
        prev = b.ts
    if duplicates:
        warnings.append(f"{duplicates} duplicate timestamps")
    if ordering:
        warnings.append(f"{ordering} bars out of time order")
    if malformed:
        warnings.append(f"{malformed} bars fail OHLC consistency")
    if len(gaps) > max_gap_report:
        warnings.append(f"{len(gaps)} time gaps detected (showing first {max_gap_report})")
        gaps = gaps[:max_gap_report]
    elif gaps:
        warnings.append(f"{len(gaps)} time gaps detected (not filled)")
    return DatasetQualityReport(
        bar_count=len(bars),
        duplicates=duplicates,
        ordering_errors=ordering,
        malformed_bars=malformed,
        gaps=gaps,
        warnings=warnings,
        coverage_start=bars[0].ts,
        coverage_end=bars[-1].ts,
        source=source,
    )


def estimate_download_cost_usd(
    provider: str,
    *,
    symbols: int,
    days: int,
    timeframe: str,
) -> dict:
    """Rough monthly cost estimator — does not charge anything."""
    provider = provider.lower()
    if provider == "yahoo":
        return {"provider": provider, "estimated_usd": 0.0, "note": "Free delayed data; 1m capped to 7 days."}
    if provider == "finzdata":
        per_day = Decimal("0.15") if timeframe == "1m" else Decimal("0.05")
        est = float(per_day * Decimal(days) * Decimal(symbols))
        return {
            "provider": provider,
            "estimated_usd": est,
            "note": "Estimate only. Paid FinzData plan required for intraday.",
            "requires_approval": True,
        }
    if provider == "databento":
        return {
            "provider": provider,
            "estimated_usd": float(Decimal("0.25") * Decimal(days) * Decimal(symbols)),
            "note": "Use POST /market-data/ingest/estimate with start/end for official get_cost when API key is set.",
            "requires_approval": True,
        }
    return {"provider": provider, "estimated_usd": None, "note": "No estimator for this provider."}