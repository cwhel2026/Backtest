"""Run certification suite and persist results."""

from __future__ import annotations

from uuid import UUID

from sqlalchemy.orm import Session

from app.models.certification import AccuracyCertificationRun
from app.services.live_lab.certification.contracts import contract_spec, validate_instrument_accounting
from app.services.live_lab.certification.parity import compare_backtest_forward
from app.services.live_lab.certification.replay import certify_replay_triple
from app.services.live_lab.certification.strategy_readiness import strategy_readiness_matrix
from app.services.instruments import _instrument_from_spec


def run_accuracy_certification(
    session: Session,
    *,
    symbol: str = "MES",
    strategy_id: UUID | None = None,
    forward_run_id: UUID | None = None,
) -> AccuracyCertificationRun:
    spec = contract_spec(symbol)
    inst_errors = validate_instrument_accounting(_instrument_from_spec(spec))
    replay = certify_replay_triple()
    parity = compare_backtest_forward({"entry": {"type": "video_anchor_bos"}})
    readiness = strategy_readiness_matrix()

    if inst_errors:
        status = "FAILED_CERTIFICATION"
        detail = "; ".join(inst_errors)
    elif not replay.passed:
        status = "FAILED_CERTIFICATION"
        detail = "; ".join(replay.divergences)
    elif (
        replay.passed
        and parity.get("parity_match")
        and readiness["video_liquidity_sweep"].get("batch_parity")
        and readiness["video_anchor_bos"].get("batch_parity")
    ):
        status = "CERTIFIED_FOR_PAPER_RESEARCH"
        detail = "Replay triple-pass; video incremental batch parity; fixture executor certified"
    elif replay.passed:
        status = "EXPERIMENTAL"
        detail = parity.get("reason", "Parity not exact — see execution_model_note")
    else:
        status = "NOT_TESTED"
        detail = "Incomplete"

    row = AccuracyCertificationRun(
        strategy_id=strategy_id,
        forward_run_id=forward_run_id,
        symbol=symbol.upper(),
        status=status,
        replay_fingerprint=replay.fingerprint,
        payload={
            "replay": {
                "passed": replay.passed,
                "divergences": replay.divergences,
                "restart_checks": replay.restart_checks,
            },
            "parity": parity,
            "contract_errors": inst_errors,
            "strategy_readiness": readiness,
            "db_integration_verified": False,
            "celery_integration_verified": False,
        },
        detail=detail,
    )
    session.add(row)
    session.flush()
    return row