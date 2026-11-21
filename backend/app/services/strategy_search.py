"""Deep search: in-memory backtests, walk-forward, reverse anti-edge, persist winners."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeout
from dataclasses import dataclass, field

from sqlalchemy.orm import Session

_BT_SEARCH_POOL = ThreadPoolExecutor(max_workers=1, thread_name_prefix="bt-search")

from app.backtest.bars import load_bars
from app.backtest.engine import BacktestAssumptions, run_backtest
from app.backtest.robustness import evaluate_robustness
from app.core.config import get_settings
from app.models.backtest import BacktestRun
from app.models.instrument import Instrument
from app.models.market_data import HistoricalDataset
from app.models.research import ResearchActivity
from app.services.backtest_runner import execute_backtest_run
from app.services.forward_sim import run_forward_simulation
from app.services.paper_book import enroll_strategy
from app.util.serde import provisional_reproducibility_id
from app.services.ai_search_mutator import propose_search_specs
from app.services.prop_screen import is_profitable_backtest, rank_score
from app.services.research_grade import (
    GRADE_KEEPER,
    HOLDOUT_FRAC,
    attach_expectancy_ci,
    research_grade,
    source_slug,
)
from app.services.search_experiment_memory import SearchExperimentMemory
from app.services.search_walkforward import (
    aggregate_fold_metrics,
    folds_pass_oos,
    split_holdout,
    walk_forward_folds,
)
from app.services.strategy_factory import create_strategy_sync
from app.services.strategy_reverse import is_anti_edge, reverse_passes_oos, reverse_spec
from app.services.strategy_search_space import refine_spec, sample_search_specs


def _split_train_test(bars: list, train_ratio: float = 0.65):
    if len(bars) < 80:
        return bars, bars[-max(20, len(bars) // 3) :]
    idx = int(len(bars) * train_ratio)
    return bars[:idx], bars[idx:]


def _metrics_for_spec(spec: dict, bars, instrument: Instrument, dataset_tf: str) -> dict | None:
    if len(bars) < 40:
        return None
    settings = get_settings()
    timeout = int(getattr(settings, "search_backtest_timeout_s", 90) or 90)

    def _run() -> dict:
        result = run_backtest(
            spec,
            bars,
            instrument,
            dataset_tf,
            BacktestAssumptions(slippage_ticks_per_side=1),
        )
        pnls = [float(t.get("net_pnl") or 0) for t in result.trades]
        seed = abs(hash(spec.get("name") or "spec")) % 10_000
        return attach_expectancy_ci(result.metrics, pnls, seed=seed)

    try:
        future = _BT_SEARCH_POOL.submit(_run)
        return future.result(timeout=timeout)
    except (FuturesTimeout, ValueError, KeyError):
        return None


def _passes_oos(test_metrics: dict | None) -> bool:
    if not test_metrics:
        return False
    net = float(test_metrics.get("total_net_profit") or 0)
    pf = test_metrics.get("profit_factor")
    trades = int(test_metrics.get("trade_count") or 0)
    return net > 0 and pf is not None and float(pf) >= 1.05 and trades >= 4


def _passes_oos_gate(test_metrics: dict | None, min_win_rate: float) -> bool:
    if not _passes_oos(test_metrics):
        return False
    wr = test_metrics.get("win_rate")
    if wr is not None and float(wr) < min_win_rate:
        return False
    return True


def _run_oos_battery(
    spec: dict,
    bars: list,
    instrument: Instrument,
    dataset_tf: str,
    *,
    n_folds: int,
    min_win_rate: float,
) -> tuple[bool, dict | None, int]:
    """Multi-fold OOS; returns (passed, aggregate metrics, backtests_run)."""
    folds = walk_forward_folds(bars, n_folds)
    runs = 0
    if len(folds) == 1:
        test_slice = folds[0][1]
        test_m = _metrics_for_spec(spec, test_slice, instrument, dataset_tf)
        runs += 1
        if not test_m:
            return False, None, runs
        ok = _passes_oos_gate(test_m, min_win_rate)
        return ok, test_m, runs

    fold_metrics: list[dict] = []
    for _train, test_slice in folds:
        m = _metrics_for_spec(spec, test_slice, instrument, dataset_tf)
        runs += 1
        if m:
            fold_metrics.append(m)
    agg = aggregate_fold_metrics(fold_metrics)
    required = 2 if len(fold_metrics) >= 3 else 1
    ok = folds_pass_oos(
        fold_metrics,
        min_folds=required,
        min_win_rate=min_win_rate,
        per_fold_check=_passes_oos,
    )
    return ok, agg, runs


def _apply_robustness(
    spec: dict,
    bars: list,
    instrument: Instrument,
    dataset_tf: str,
    full_m: dict,
) -> tuple[dict | None, int]:
    settings = get_settings()
    if not bool(getattr(settings, "search_robustness_enabled", True)):
        return full_m, 0
    n_shuffles = int(getattr(settings, "search_robustness_shuffles", 8) or 8)
    slip = int(getattr(settings, "search_stress_slip_ticks", 2) or 2)
    min_pass = float(getattr(settings, "search_robustness_min_pass", 0.5) or 0.5)
    report = evaluate_robustness(
        spec,
        bars,
        instrument,
        dataset_tf,
        n_shuffles=n_shuffles,
        slip_ticks=slip,
        min_pass=min_pass,
        seed=abs(hash(spec.get("name") or "spec")) % 10_000,
    )
    if not report["passed"]:
        return None, int(report["backtests"])
    return {**full_m, **report["metrics"]}, int(report["backtests"])


def _attach_holdout_and_grade(
    spec: dict,
    full_m: dict,
    test_m: dict | None,
    holdout: list,
    instrument: Instrument,
    timeframe: str,
    *,
    origin: str,
    data_source: str,
    sample_days: float | None,
) -> dict:
    holdout_m = None
    if holdout and len(holdout) >= 40:
        holdout_m = _metrics_for_spec(spec, holdout, instrument, timeframe)
    graded = dict(full_m)
    if holdout_m:
        graded["holdout_net"] = holdout_m.get("total_net_profit")
        graded["holdout_trades"] = holdout_m.get("trade_count")
        graded["holdout_win_rate"] = holdout_m.get("win_rate")
        graded["holdout_profit_factor"] = holdout_m.get("profit_factor")
    graded["data_source"] = data_source
    graded["grade"] = research_grade(
        graded,
        oos=test_m,
        holdout=holdout_m,
        reverse=origin == "reverse",
        timeframe=timeframe,
        data_source=data_source,
        sample_days=sample_days,
    )
    return graded


@dataclass
class SearchHit:
    spec: dict
    train_metrics: dict
    test_metrics: dict
    full_metrics: dict
    score: float
    origin: str = "deep"
    original_metrics: dict | None = field(default=None)
    robustness: dict | None = field(default=None)


def _consider(
    spec: dict,
    train_m: dict,
    test_m: dict,
    full_m: dict,
    *,
    origin: str,
    original_metrics: dict | None,
    leaderboard: list,
    timeframe: str,
) -> None:
    reverse = origin == "reverse"
    if not full_m or not is_profitable_backtest(full_m, reverse=reverse, timeframe=timeframe):
        return
    sc = rank_score(full_m)
    if reverse:
        wr = float(full_m.get("win_rate") or 0)
        sc += wr * 400
    leaderboard.append((sc, spec, full_m, test_m, train_m, origin, original_metrics))


def run_deep_search(
    session: Session,
    *,
    symbol: str,
    dataset: HistoricalDataset,
    instrument: Instrument,
    budget: int,
    refine_top: int = 8,
    seed: int | None = None,
    on_progress=None,
) -> tuple[list[SearchHit], int, dict]:
    settings = get_settings()
    wr_max = float(getattr(settings, "reverse_winrate_max", 0.20) or 0.20)
    reverse_on = bool(getattr(settings, "reverse_search_enabled", True))
    n_folds = int(getattr(settings, "search_walkforward_folds", 3) or 3)
    oos_min_wr = float(getattr(settings, "search_oos_min_win_rate", 0.38) or 0.38)
    ai_rounds = int(getattr(settings, "search_ai_rounds", 0) or 0)
    ai_batch = int(getattr(settings, "search_ai_specs_per_round", 12) or 12)
    if settings.ai_configured and ai_rounds < 1:
        ai_rounds = 1

    from app.services.market_data.dataset_research import prepare_dataset_for_research

    elig = prepare_dataset_for_research(session, dataset)
    if not elig.ok:
        stats = {"skipped": elig.reason, "lineage": elig.lineage}
        return [], 0, stats

    bars = load_bars(session, dataset.id)
    if not bars:
        return [], 0, {"skipped": "no bars in store", "lineage": elig.lineage}
    research, holdout = split_holdout(bars, HOLDOUT_FRAC)
    train, _test = _split_train_test(research)
    tf = dataset.timeframe
    data_source = source_slug(str((dataset.meta or {}).get("source") or ""))
    sample_days = None
    if dataset.coverage_start and dataset.coverage_end:
        sample_days = max((dataset.coverage_end - dataset.coverage_start).total_seconds(), 0) / 86400

    specs = sample_search_specs(symbol, budget, seed=seed, timeframe=tf)
    evaluated = 0
    leaderboard: list = []
    closest: list[tuple[float, dict, dict]] = []
    refine_queue: list[dict] = []
    reverse_queue: list[tuple[dict, dict]] = []
    memory = SearchExperimentMemory(symbol=symbol)
    tried_names: set[str] = {s["name"] for s in specs}

    def _remember(spec: dict, metrics: dict | None) -> None:
        if not metrics or int(metrics.get("trade_count") or 0) < 4:
            return
        closest.append((float(metrics.get("total_net_profit") or 0), spec, metrics))

    def _tick(spec: dict | None = None, *, subphase: str = "walk_forward") -> None:
        if not on_progress:
            return
        if evaluated > 0 and evaluated % 4 != 0 and evaluated > 24:
            return
        on_progress(evaluated, spec=spec, subphase=subphase)

    def _score_forward(
        spec: dict,
        *,
        origin: str,
        sub_train: str,
        sub_oos: str,
        sub_full: str,
        original_metrics: dict | None = None,
    ) -> None:
        nonlocal evaluated
        train_m = _metrics_for_spec(spec, train, instrument, tf)
        evaluated += 1
        _tick(spec, subphase=sub_train)
        if not train_m:
            return
        _remember(spec, train_m)
        pf = float(train_m.get("profit_factor") or 0)
        net = float(train_m.get("total_net_profit") or 0)
        if origin == "deep" and (pf >= 0.92 or net > 0):
            refine_queue.append(spec)
        if origin == "deep" and reverse_on and is_anti_edge(train_m, winrate_max=wr_max):
            reverse_queue.append((spec, train_m))
        if net <= 0:
            memory.record(spec, train_m, outcome="train_reject", note="negative train net")
            return

        passed_oos, test_m, oos_runs = _run_oos_battery(
            spec, research, instrument, tf, n_folds=n_folds, min_win_rate=oos_min_wr
        )
        evaluated += oos_runs
        _tick(spec, subphase=sub_oos)
        if not passed_oos or not test_m:
            memory.record(
                spec,
                test_m or train_m,
                outcome="oos_fail",
                note=f"failed {n_folds}-fold OOS (min WR {oos_min_wr:.0%})",
            )
            return

        full_m = _metrics_for_spec(spec, research, instrument, tf)
        evaluated += 1
        _tick(spec, subphase=sub_full)
        reverse = origin == "reverse"
        if not full_m or not is_profitable_backtest(full_m, reverse=reverse, timeframe=tf):
            memory.record(spec, full_m or test_m, outcome="prop_reject", note="prop screen")
            return

        full_m, extra = _apply_robustness(spec, research, instrument, tf, full_m)
        evaluated += extra
        _tick(spec, subphase="robustness")
        if not full_m:
            memory.record(spec, test_m, outcome="robust_fail", note="cost/MC/neighborhood")
            return

        full_m = _attach_holdout_and_grade(
            spec,
            full_m,
            test_m,
            holdout,
            instrument,
            tf,
            origin=origin,
            data_source=data_source,
            sample_days=sample_days,
        )
        if holdout:
            evaluated += 1
            _tick(spec, subphase="holdout")

        memory.record(spec, full_m, outcome="winner", note=origin)
        _consider(
            spec,
            train_m,
            test_m,
            full_m,
            origin=origin,
            original_metrics=original_metrics,
            leaderboard=leaderboard,
            timeframe=tf,
        )

    for spec in specs:
        _score_forward(spec, origin="deep", sub_train="train", sub_oos="oos", sub_full="prop_screen")

    for spec, orig_train in reverse_queue[: max(24, refine_top * 3)]:
        rev = reverse_spec(spec, original_metrics=orig_train)
        if not rev:
            continue
        train_m = _metrics_for_spec(rev, train, instrument, tf)
        evaluated += 1
        _tick(rev, subphase="reverse_train")
        if not train_m or float(train_m.get("total_net_profit") or 0) <= 0:
            continue
        passed_oos, test_m, oos_runs = _run_oos_battery(
            rev, research, instrument, tf, n_folds=n_folds, min_win_rate=oos_min_wr
        )
        evaluated += oos_runs
        _tick(rev, subphase="reverse_oos")
        orig_wr = orig_train.get("win_rate")
        if not passed_oos or not test_m or not reverse_passes_oos(
            test_m, float(orig_wr) if orig_wr is not None else None
        ):
            continue
        full_m = _metrics_for_spec(rev, research, instrument, tf)
        evaluated += 1
        _tick(rev, subphase="reverse_full")
        if full_m and is_profitable_backtest(full_m, reverse=True, timeframe=tf):
            full_m, extra = _apply_robustness(rev, research, instrument, tf, full_m)
            evaluated += extra
            _tick(rev, subphase="robustness")
            if not full_m:
                memory.record(rev, test_m, outcome="robust_fail", note="reverse robustness")
                continue
            full_m = _attach_holdout_and_grade(
                rev,
                full_m,
                test_m,
                holdout,
                instrument,
                tf,
                origin="reverse",
                data_source=data_source,
                sample_days=sample_days,
            )
            if holdout:
                evaluated += 1
                _tick(rev, subphase="holdout")
            memory.record(rev, full_m, outcome="winner", note="reverse")
            _consider(
                rev,
                train_m,
                test_m,
                full_m,
                origin="reverse",
                original_metrics=orig_train,
                leaderboard=leaderboard,
                timeframe=tf,
            )

    for base in refine_queue[: refine_top]:
        for refined in refine_spec(base):
            if refined["name"] in tried_names:
                continue
            tried_names.add(refined["name"])
            _score_forward(
                refined,
                origin="deep",
                sub_train="refine_train",
                sub_oos="refine_oos",
                sub_full="refine_full",
            )

    for ai_idx in range(ai_rounds):
        _tick(subphase="ai_propose")
        summary = memory.summary_for_ai()
        rationale, ai_specs = propose_search_specs(
            symbol,
            summary,
            max_specs=ai_batch,
            seed=(seed or 0) + 9000 + ai_idx,
        )
        for spec in ai_specs:
            if spec["name"] in tried_names:
                spec["name"] = f"{spec['name']} r{ai_idx}"
            tried_names.add(spec["name"])
            _score_forward(
                spec,
                origin="ai",
                sub_train="ai_train",
                sub_oos="ai_oos",
                sub_full="ai_prop",
            )

    leaderboard.sort(key=lambda x: x[0], reverse=True)
    seen_names: set[str] = set()
    hits: list[SearchHit] = []
    for sc, spec, full_m, test_m, train_m, origin, original_metrics in leaderboard:
        if spec["name"] in seen_names:
            continue
        seen_names.add(spec["name"])
        hits.append(
            SearchHit(
                spec=spec,
                train_metrics=train_m,
                test_metrics=test_m,
                full_metrics=full_m,
                score=sc,
                origin=origin,
                original_metrics=original_metrics,
            )
        )
        if len(hits) >= 8:
            break

    closest.sort(key=lambda row: row[0], reverse=True)
    near = 0
    for _net, spec, train_m in closest:
        if spec["name"] in seen_names:
            continue
        seen_names.add(spec["name"])
        hits.append(
            SearchHit(
                spec=spec,
                train_metrics=train_m,
                test_metrics=train_m,
                full_metrics=train_m,
                score=_net,
                origin="near_miss",
            )
        )
        near += 1
        if near >= 2:
            break

    stats = memory.to_progress_blob()
    stats["ai_rounds"] = ai_rounds
    stats["grid_specs"] = len(specs)
    return hits, evaluated, stats


def persist_search_hits(
    session: Session,
    hits: list[SearchHit],
    dataset: HistoricalDataset,
    symbol: str,
    *,
    actor: str,
    forward_sim: bool,
) -> list[str]:
    winners: list[str] = []
    for hit in hits:
        try:
            _persist_one_hit(session, hit, dataset, symbol, actor, forward_sim, winners)
        except Exception as exc:
            session.rollback()
            session.add(
                ResearchActivity(
                    headline=f"Skip persist {symbol}",
                    detail=str(exc)[:300],
                    meta={"symbol": symbol, "hit": hit.spec.get("name")},
                )
            )
            session.flush()
    return winners


def _persist_one_hit(
    session: Session,
    hit: SearchHit,
    dataset: HistoricalDataset,
    symbol: str,
    actor: str,
    forward_sim: bool,
    winners: list[str],
) -> None:
    orig_wr = (hit.original_metrics or {}).get("win_rate") if hit.origin == "reverse" else None
    oos_wr = hit.test_metrics.get("win_rate")
    if hit.origin == "near_miss":
        rationale = (
            f"Closest {symbol} test this search (did not pass the prop screen). "
            f"Train net {hit.train_metrics.get('total_net_profit')}."
        )
    elif hit.origin == "reverse" and orig_wr is not None:
        rationale = (
            f"Reverse of anti-edge on {symbol}: original train WR {float(orig_wr):.0%} "
            f"(implied fade {1 - float(orig_wr):.0%}). OOS WR {float(oos_wr or 0):.0%}, "
            f"OOS net {hit.test_metrics.get('total_net_profit')}."
        )
    elif hit.origin == "ai":
        rationale = (
            f"AI-directed search winner on {symbol}. Train net {hit.train_metrics.get('total_net_profit')}, "
            f"OOS net {hit.test_metrics.get('total_net_profit')} (multi-fold when configured)."
        )
    else:
        rationale = (
            f"Deep search winner on {symbol}. Train net {hit.train_metrics.get('total_net_profit')}, "
            f"OOS net {hit.test_metrics.get('total_net_profit')}."
        )
    strategy = create_strategy_sync(
        session,
        specification=hit.spec,
        economic_rationale=rationale,
        created_by=actor,
    )
    session.flush()
    run = BacktestRun(
        strategy_id=strategy.id,
        strategy_version_id=strategy.current_version_id,
        dataset_id=dataset.id,
        status="queued",
        engine_version="pending",
        reproducibility_id=provisional_reproducibility_id(),
        assumptions={"slippage_ticks_per_side": 1},
        parameters={
            "search": hit.origin,
            "origin": hit.origin,
            "oos_metrics": hit.test_metrics,
            "train_metrics": hit.train_metrics,
            "original_metrics": hit.original_metrics,
            "grade": hit.full_metrics.get("grade"),
            "data_source": hit.full_metrics.get("data_source"),
            "holdout_metrics": {
                "total_net_profit": hit.full_metrics.get("holdout_net"),
                "trade_count": hit.full_metrics.get("holdout_trades"),
                "win_rate": hit.full_metrics.get("holdout_win_rate"),
                "profit_factor": hit.full_metrics.get("holdout_profit_factor"),
            }
            if hit.full_metrics.get("holdout_net") is not None
            else None,
            "robustness": {
                k: hit.full_metrics.get(k)
                for k in (
                    "mc_pass_rate",
                    "mc_median_net",
                    "neighborhood_pass_rate",
                    "stress_slip_net",
                    "robustness_score",
                )
                if hit.full_metrics.get(k) is not None
            },
        },
    )
    session.add(run)
    session.flush()
    from app.services.market_data.dataset_research import prepare_dataset_for_research

    persist_elig = prepare_dataset_for_research(session, dataset)
    if not persist_elig.genuine_persist:
        session.delete(run)
        session.flush()
        return
    try:
        execute_backtest_run(session, run.id)
    except ValueError as exc:
        run.status = "failed"
        run.error = str(exc)[:500]
        session.flush()
        return
    if run.status == "completed" and isinstance(run.metrics, dict):
        extra = {
            k: hit.full_metrics.get(k)
            for k in (
                "mc_pass_rate",
                "mc_median_net",
                "neighborhood_pass_rate",
                "stress_slip_net",
                "stress_slip_pf",
                "robustness_score",
                "grade",
                "expectancy_ci_low",
                "expectancy_ci_high",
                "expectancy_ci_includes_zero",
                "holdout_net",
                "holdout_trades",
                "holdout_win_rate",
                "holdout_profit_factor",
                "data_source",
            )
            if hit.full_metrics.get(k) is not None
        }
        merged = {**run.metrics, **extra}
        if not merged.get("grade"):
            src = extra.get("data_source") or source_slug(str((dataset.meta or {}).get("source") or ""))
            merged["grade"] = research_grade(
                merged,
                oos=hit.test_metrics,
                reverse=hit.origin == "reverse",
                timeframe=dataset.timeframe,
                data_source=src,
            )
            merged["data_source"] = src
        run.metrics = merged
        session.add(run)
    grade = (run.metrics or {}).get("grade") if isinstance(run.metrics, dict) else None
    if run.status == "completed" and grade == GRADE_KEEPER:
        enroll_strategy(session, strategy, symbol)
    session.commit()
    winners.append(strategy.name)

    if forward_sim and run.status == "completed":
        sim = run_forward_simulation(session, strategy, run, tail_bars=120)
        prefix = "Reverse candidate" if hit.origin == "reverse" else "Prop candidate"
        wr_bit = ""
        if hit.origin == "reverse" and orig_wr is not None:
            wr_bit = f" · fade {float(orig_wr):.0%}→{float(oos_wr or 0):.0%} WR"
        session.add(
            ResearchActivity(
                headline=f"{prefix} · {strategy.name}",
                detail=(
                    f"{symbol}{wr_bit} · OOS PF {float(hit.test_metrics.get('profit_factor') or 0):.2f} · "
                    f"full net ${float(hit.full_metrics.get('total_net_profit') or 0):.0f} · {sim.get('summary', '')}"
                ),
                meta={
                    "strategy_id": str(strategy.id),
                    "run_id": str(run.id),
                    "origin": hit.origin,
                    "hit": hit.full_metrics,
                },
            )
        )
        session.commit()
