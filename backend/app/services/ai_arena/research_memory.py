"""Structured per-researcher memory — compact retrieval for LLM context."""

from __future__ import annotations

from sqlalchemy.orm import Session

from app.models.ai_arena import AiExperiment, AiResearcher


def memory_context_for_llm(researcher: AiResearcher) -> dict:
    """Bounded summary; never the full experiment table."""
    mem = dict(researcher.memory or {})
    return {
        "objectives": researcher.objectives,
        "successful_traits": (mem.get("successful_traits") or [])[-12:],
        "failed_hypotheses": (mem.get("failed_hypotheses") or [])[-15:],
        "tested_param_ranges": mem.get("tested_param_ranges") or {},
        "instrument_notes": mem.get("instrument_notes") or {},
        "weak_execution_patterns": (mem.get("weak_execution_patterns") or [])[-8:],
        "families_to_avoid": (mem.get("failed_families") or [])[-10:],
        "families_working": (mem.get("working_families") or [])[-6:],
        "recent_compact": (mem.get("recent_compact") or [])[-10:],
    }


def update_memory_from_experiment(researcher: AiResearcher, experiment: AiExperiment) -> None:
    mem = dict(researcher.memory or {})
    spec = experiment.specification or {}
    entry = spec.get("entry") or {}
    exit_s = spec.get("exit") or {}
    sym = experiment.symbol
    compact = {
        "id": str(experiment.id),
        "status": experiment.status,
        "tier": experiment.validation_tier,
        "family": experiment.strategy_family,
        "symbol": sym,
        "entry_type": entry.get("type"),
        "metrics": {
            k: experiment.validation_metrics.get(k)
            for k in ("trade_count", "profit_factor", "net_pnl", "max_drawdown", "oos_passed")
            if isinstance(experiment.validation_metrics, dict)
        },
        "reason": (experiment.rejection_reason or "")[:160],
        "parent_id": str(experiment.parent_experiment_id) if experiment.parent_experiment_id else None,
    }
    mem["recent_compact"] = (mem.get("recent_compact") or [])[-49:] + [compact]

    if experiment.status == "validated":
        traits = mem.get("successful_traits") or []
        traits.append(
            {
                "family": experiment.strategy_family,
                "entry_type": entry.get("type"),
                "symbol": sym,
                "profit_factor": experiment.validation_metrics.get("profit_factor"),
            }
        )
        mem["successful_traits"] = traits[-20:]
        wf = mem.get("working_families") or []
        if experiment.strategy_family not in wf:
            wf.append(experiment.strategy_family)
        mem["working_families"] = wf[-12:]
    else:
        fails = mem.get("failed_hypotheses") or []
        fails.append(
            {
                "hypothesis": experiment.hypothesis[:200],
                "family": experiment.strategy_family,
                "reason": (experiment.rejection_reason or experiment.status)[:200],
            }
        )
        mem["failed_hypotheses"] = fails[-30:]
        ff = mem.get("failed_families") or []
        if experiment.strategy_family and experiment.strategy_family not in ff:
            ff.append(experiment.strategy_family)
        mem["failed_families"] = ff[-20:]

    ranges = dict(mem.get("tested_param_ranges") or {})
    etype = entry.get("type") or "unknown"
    key = f"{sym}:{etype}"
    bucket = ranges.setdefault(key, [])
    bucket.append({"stop": exit_s.get("stop_ticks"), "target": exit_s.get("target_ticks"), "status": experiment.status})
    ranges[key] = bucket[-12:]
    mem["tested_param_ranges"] = ranges

    inst_notes = dict(mem.get("instrument_notes") or {})
    note = inst_notes.get(sym) or {"wins": 0, "losses": 0}
    if experiment.status == "validated":
        note["wins"] = int(note.get("wins", 0)) + 1
    elif experiment.status == "rejected":
        note["losses"] = int(note.get("losses", 0)) + 1
    inst_notes[sym] = note
    mem["instrument_notes"] = inst_notes

    vm = experiment.validation_metrics or {}
    if int(vm.get("trade_count") or 0) < 10:
        weak = mem.get("weak_execution_patterns") or []
        weak.append(f"Low sample on {sym} {etype}")
        mem["weak_execution_patterns"] = weak[-15:]

    researcher.memory = mem