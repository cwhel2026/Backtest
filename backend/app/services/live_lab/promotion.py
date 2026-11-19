"""Forward-test promotion gates — manual override allowed with experimental flag."""

from __future__ import annotations

from decimal import Decimal
from uuid import UUID

from sqlalchemy import desc, select
from sqlalchemy.orm import Session

from app.models.backtest import BacktestRun
from app.models.enums import ForwardTestState, StrategyLifecycle
from app.models.strategy import StrategyDefinition, StrategyVersion


def evaluate_historical_validation(session: Session, strategy_id: UUID) -> tuple[bool, list[str], dict]:
    """Configurable gates from latest completed backtest metrics."""
    reasons: list[str] = []
    strategy = session.get(StrategyDefinition, strategy_id)
    if not strategy:
        return False, ["strategy_not_found"], {}
    run = session.execute(
        select(BacktestRun)
        .where(BacktestRun.strategy_id == strategy_id, BacktestRun.status == "completed")
        .order_by(desc(BacktestRun.completed_at))
        .limit(1)
    ).scalar_one_or_none()
    if not run or not run.metrics:
        reasons.append("no_completed_backtest")
        return False, reasons, {}
    m = run.metrics
    gates: dict = {}
    min_trades = 20
    trades = int(m.get("trade_count") or m.get("trades") or 0)
    gates["trade_count"] = trades
    if trades < min_trades:
        reasons.append(f"min_trades_{min_trades}")
    exp = m.get("expectancy") or m.get("net_expectancy")
    if exp is not None and Decimal(str(exp)) <= 0:
        reasons.append("non_positive_expectancy")
    gates["expectancy"] = exp
    max_dd = m.get("max_drawdown") or m.get("max_drawdown_abs")
    gates["max_drawdown"] = max_dd
    if max_dd is not None and Decimal(str(max_dd)) > Decimal("15000"):
        reasons.append("drawdown_too_high")
    oos = m.get("oos_pass") or m.get("walk_forward_pass")
    gates["oos_pass"] = oos
    if oos is False:
        reasons.append("walk_forward_failed")
    genuine = m.get("genuine_for_research") or m.get("data_genuine")
    gates["genuine_data"] = genuine
    if genuine is False:
        reasons.append("data_not_genuine")
    passed = len(reasons) == 0
    return passed, reasons, gates


def default_research_state(session: Session, strategy_id: UUID, *, experimental: bool) -> ForwardTestState:
    if experimental:
        return ForwardTestState.FORWARD_TEST_PENDING
    ok, _, _ = evaluate_historical_validation(session, strategy_id)
    if ok:
        return ForwardTestState.HISTORICALLY_VALIDATED
    strat = session.get(StrategyDefinition, strategy_id)
    if strat and strat.lifecycle == StrategyLifecycle.HISTORICALLY_VALIDATED:
        return ForwardTestState.HISTORICALLY_VALIDATED
    return ForwardTestState.FORWARD_TEST_PENDING


def freeze_strategy_version(session: Session, strategy_id: UUID) -> StrategyVersion | None:
    strat = session.get(StrategyDefinition, strategy_id)
    if not strat or not strat.current_version_id:
        return None
    return session.get(StrategyVersion, strat.current_version_id)