"""Single home dashboard payload — non-technical summary labels."""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import desc, func, select
from sqlalchemy.orm import Session

from app.models.backtest import BacktestRun
from app.models.enums import ScannerSetupStatus
from app.models.instrument import Instrument
from app.models.live_lab import ForwardTestRun, LiveCompletedCandle
from app.models.scanner import ScannerSetup, WorkerHealthBeat
from app.models.strategy import StrategyDefinition
from app.services.live_lab.service import dashboard_summary
from app.services.platform_status import build_platform_status


def _active_statuses() -> list[str]:
    return [
        ScannerSetupStatus.DETECTED.value,
        ScannerSetupStatus.PENDING_ENTRY.value,
        ScannerSetupStatus.FILLED_PAPER.value,
    ]


def build_home_dashboard(session: Session, *, symbols: list[str]) -> dict:
    platform = build_platform_status(session)
    paper = dashboard_summary(session)

    now = datetime.now(UTC)
    day_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    setups_today = session.execute(
        select(func.count()).select_from(ScannerSetup).where(ScannerSetup.detected_at >= day_start)
    ).scalar_one()
    active_setups = session.execute(
        select(func.count()).select_from(ScannerSetup).where(ScannerSetup.status.in_(_active_statuses()))
    ).scalar_one()
    forward_beat = session.execute(
        select(WorkerHealthBeat).where(WorkerHealthBeat.worker_name == "live_lab_forward")
    ).scalar_one_or_none()
    from app.services.worker_health import worker_is_stale

    scanner_running = bool(forward_beat and not worker_is_stale(forward_beat, now=now))
    completed_setups = session.execute(
        select(func.count())
        .select_from(ScannerSetup)
        .where(ScannerSetup.status.in_([ScannerSetupStatus.TP_HIT.value, ScannerSetupStatus.SL_HIT.value]))
    ).scalar_one()

    latest = session.execute(select(ScannerSetup).order_by(desc(ScannerSetup.detected_at)).limit(12)).scalars().all()

    markets: list[dict] = []
    for sym in symbols:
        inst = session.execute(select(Instrument).where(Instrument.symbol == sym)).scalar_one_or_none()
        candle = session.execute(
            select(LiveCompletedCandle)
            .where(LiveCompletedCandle.symbol == sym, LiveCompletedCandle.timeframe == "5m")
            .order_by(LiveCompletedCandle.ts.desc())
            .limit(1)
        ).scalar_one_or_none()
        markets.append(
            {
                "symbol": sym,
                "display_name": inst.name if inst else sym,
                "last_price": float(candle.close) if candle else None,
                "last_candle_ts": candle.ts.isoformat() if candle else None,
                "data_source": candle.source if candle else None,
                "latency_mode": platform["market_data"]["latency_mode"],
                "session_status": "stored_candles",
            }
        )

    runs_open = session.execute(
        select(func.count())
        .select_from(ForwardTestRun)
        .where(ForwardTestRun.trade_count > 0, ForwardTestRun.net_pnl.isnot(None))
    ).scalar_one()

    bt_rows = session.execute(select(BacktestRun).order_by(desc(BacktestRun.created_at)).limit(8)).scalars().all()
    recent_backtests: list[dict] = []
    for run in bt_rows:
        strat = session.get(StrategyDefinition, run.strategy_id)
        inst_id = (run.assumptions or {}).get("instrument_symbol")
        m = run.metrics or {}
        recent_backtests.append(
            {
                "id": str(run.id),
                "strategy_name": strat.name if strat else "Strategy",
                "instrument": inst_id or "—",
                "status": run.status,
                "period": (run.assumptions or {}).get("date_range_label") or "See report",
                "trade_count": m.get("trade_count"),
                "net_pnl": m.get("net_profit_usd"),
                "win_rate": m.get("win_rate"),
                "max_drawdown": m.get("max_drawdown_usd"),
                "validation_status": run.performance_category.value if run.performance_category else None,
                "completed_at": run.completed_at.isoformat() if run.completed_at else None,
            }
        )

    agg = paper
    wins = sum(r["win_rate"] or 0 for r in agg["runs"] if r.get("win_rate"))
    wr_runs = [r for r in agg["runs"] if r.get("win_rate") is not None]

    return {
        "summary": {
            "markets_monitored": len(symbols),
            "active_setups": int(active_setups or 0),
            "setups_today": int(setups_today or 0),
            "scanner_running": scanner_running,
            "completed_setups": int(completed_setups or 0),
            "open_paper_runs": int(agg["active_strategy_count"] or 0),
            "paper_trades_recorded": int(runs_open or 0),
            "research_strategies_evaluated": len(recent_backtests),
        },
        "workers_and_data": platform.get("workers", []),
        "database_ok": platform.get("database", {}).get("ok"),
        "redis_ok": platform.get("redis", {}).get("ok"),
        "market_data_status": platform["market_data"],
        "platform": platform,
        "markets": markets,
        "latest_setups": [_setup_card(s) for s in latest],
        "paper_performance": {
            "realised_net_pnl": float(agg["aggregate_net_pnl"] or 0),
            "open_equity": float(agg["aggregate_equity"] or 0),
            "avg_win_rate": (wins / len(wr_runs)) if wr_runs else None,
            "trade_count": sum(r.get("trade_count") or 0 for r in agg["runs"]),
            "runs": agg["runs"],
            "disclaimer": agg["disclaimer"],
        },
        "recent_backtests": recent_backtests,
    }


def _setup_card(s: ScannerSetup) -> dict:
    return {
        "id": str(s.id),
        "setup_id": s.setup_id,
        "strategy": s.strategy_name,
        "instrument": s.symbol,
        "direction": s.direction,
        "entry": float(s.entry_price) if s.entry_price is not None else None,
        "stop_loss": float(s.stop_price) if s.stop_price is not None else None,
        "target": float(s.target_price) if s.target_price is not None else None,
        "risk_reward": float(s.risk_reward) if s.risk_reward is not None else None,
        "status": s.status,
        "market_ts": s.market_ts.isoformat(),
        "explanation": s.explanation,
        "feed_latency_mode": s.feed_latency_mode,
    }