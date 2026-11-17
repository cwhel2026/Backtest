"""Deep search: in-memory backtests, walk-forward, reverse anti-edge, persist winners."""

from __future__ import annotations

from dataclasses import dataclass, field

from sqlalchemy.orm import Session

from app.backtest.bars import load_bars
from app.backtest.engine import BacktestAssumptions, run_backtest
from app.core.config import get_settings
from app.models.backtest import BacktestRun
from app.models.instrument import Instrument
from app.models.market_data import HistoricalDataset
from app.models.research import ResearchActivity
from app.services.backtest_runner import execute_backtest_run
from app.services.forward_sim import run_forward_simulation
from app.services.paper_book import enroll_strategy
from app.services.prop_screen import is_profitable_backtest, rank_score
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
    try:
        result = run_backtest(
            spec,
            bars,
            instrument,
            dataset_tf,
            BacktestAssumptions(slippage_ticks_per_side=1),
        )
        return result.metrics
    except (ValueError, KeyError):
        return None


def _passes_oos(test_metrics: dict | None) -> bool:
    if not test_metrics:
        return False
    net = float(test_metrics.get("total_net_profit") or 0)
    pf = test_metrics.get("profit_factor")
    trades = int(test_metrics.get("trade_count") or 0)
    return net > 0 and pf is not None and float(pf) >= 1.05 and trades >= 4


@dataclass
class SearchHit:
    spec: dict
    train_metrics: dict
    test_metrics: dict
    full_metrics: dict
    score: float
    origin: str = "deep"
    original_metrics: dict | None = field(default=None)


def _consider(
    spec: dict,
    train_m: dict,
    test_m: dict,
    full_m: dict,
    *,
    origin: str,
    original_metrics: dict | None,
    leaderboard: list,
) -> None:
    reverse = origin == "reverse"
    if not full_m or not is_profitable_backtest(full_m, reverse=reverse):
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
) -> tuple[list[SearchHit], int]:
    settings = get_settings()
    wr_max = float(getattr(settings, "reverse_winrate_max", 0.20) or 0.20)
    reverse_on = bool(getattr(settings, "reverse_search_enabled", True))

    bars = load_bars(session, dataset.id)
    train, test = _split_train_test(bars)
    tf = dataset.timeframe

    specs = sample_search_specs(symbol, budget, seed=seed)
    evaluated = 0
    leaderboard: list = []
    refine_queue: list[dict] = []
    reverse_queue: list[tuple[dict, dict]] = []

    for spec in specs:
        train_m = _metrics_for_spec(spec, train, instrument, tf)
        evaluated += 1
        if not train_m:
            continue
        pf = float(train_m.get("profit_factor") or 0)
        net = float(train_m.get("total_net_profit") or 0)
        if pf >= 0.92 or net > 0:
            refine_queue.append(spec)
        if reverse_on and is_anti_edge(train_m, winrate_max=wr_max):
            reverse_queue.append((spec, train_m))
        if net <= 0:
            continue
        test_m = _metrics_for_spec(spec, test, instrument, tf)
        evaluated += 1
        if not _passes_oos(test_m):
            continue
        full_m = _metrics_for_spec(spec, bars, instrument, tf)
        evaluated += 1
        _consider(spec, train_m, test_m, full_m, origin="deep", original_metrics=None, leaderboard=leaderboard)

    for spec, orig_train in reverse_queue[: max(24, refine_top * 3)]:
        rev = reverse_spec(spec, original_metrics=orig_train)
        if not rev:
            continue
        train_m = _metrics_for_spec(rev, train, instrument, tf)
        evaluated += 1
        if not train_m or float(train_m.get("total_net_profit") or 0) <= 0:
            continue
        test_m = _metrics_for_spec(rev, test, instrument, tf)
        evaluated += 1
        orig_wr = orig_train.get("win_rate")
        if not reverse_passes_oos(test_m, float(orig_wr) if orig_wr is not None else None):
            continue
        full_m = _metrics_for_spec(rev, bars, instrument, tf)
        evaluated += 1
        _consider(
            rev,
            train_m,
            test_m,
            full_m,
            origin="reverse",
            original_metrics=orig_train,
            leaderboard=leaderboard,
        )

    for base in refine_queue[:refine_top]:
        for refined in refine_spec(base):
            train_m = _metrics_for_spec(refined, train, instrument, tf)
            evaluated += 1
            if not train_m or float(train_m.get("total_net_profit") or 0) <= 0:
                continue
            test_m = _metrics_for_spec(refined, test, instrument, tf)
            evaluated += 1
            if not _passes_oos(test_m):
                continue
            full_m = _metrics_for_spec(refined, bars, instrument, tf)
            evaluated += 1
            _consider(
                refined,
                train_m,
                test_m,
                full_m,
                origin="deep",
                original_metrics=None,
                leaderboard=leaderboard,
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

    return hits, evaluated


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
        orig_wr = (hit.original_metrics or {}).get("win_rate") if hit.origin == "reverse" else None
        oos_wr = hit.test_metrics.get("win_rate")
        if hit.origin == "reverse" and orig_wr is not None:
            rationale = (
                f"Reverse of anti-edge on {symbol}: original train WR {float(orig_wr):.0%} "
                f"(implied fade {1 - float(orig_wr):.0%}). OOS WR {float(oos_wr or 0):.0%}, "
                f"OOS net {hit.test_metrics.get('total_net_profit')}."
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
            reproducibility_id="pending",
            assumptions={"slippage_ticks_per_side": 1},
            parameters={
                "search": "reverse_anti_edge" if hit.origin == "reverse" else "deep_walk_forward",
                "origin": hit.origin,
                "oos_metrics": hit.test_metrics,
                "train_metrics": hit.train_metrics,
                "original_metrics": hit.original_metrics,
            },
        )
        session.add(run)
        session.flush()
        execute_backtest_run(session, run.id)
        if run.status == "completed":
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
    return winners
