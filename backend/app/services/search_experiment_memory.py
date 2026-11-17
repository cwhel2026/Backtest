"""In-run experiment memory for AI-directed search mutations."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class TrialRecord:
    name: str
    entry_type: str
    net: float
    win_rate: float | None
    profit_factor: float | None
    trades: int
    outcome: str
    note: str = ""


@dataclass
class SearchExperimentMemory:
    symbol: str
    trials: list[TrialRecord] = field(default_factory=list)

    def record(self, spec: dict, metrics: dict[str, Any] | None, *, outcome: str, note: str = "") -> None:
        if not metrics:
            return
        entry = (spec.get("entry") or {}).get("type") or "?"
        self.trials.append(
            TrialRecord(
                name=str(spec.get("name", "?"))[:80],
                entry_type=str(entry),
                net=float(metrics.get("total_net_profit") or 0),
                win_rate=float(metrics["win_rate"]) if metrics.get("win_rate") is not None else None,
                profit_factor=float(metrics["profit_factor"]) if metrics.get("profit_factor") is not None else None,
                trades=int(metrics.get("trade_count") or 0),
                outcome=outcome,
                note=note[:200],
            )
        )
        if len(self.trials) > 120:
            self.trials = self.trials[-120:]

    def family_stats(self) -> dict[str, dict[str, float]]:
        stats: dict[str, dict[str, list[float]]] = {}
        for t in self.trials:
            bucket = stats.setdefault(t.entry_type, {"net": [], "wr": []})
            bucket["net"].append(t.net)
            if t.win_rate is not None:
                bucket["wr"].append(t.win_rate)
        out: dict[str, dict[str, float]] = {}
        for fam, vals in stats.items():
            nets = vals["net"]
            wrs = vals["wr"]
            out[fam] = {
                "count": float(len(nets)),
                "avg_net": sum(nets) / max(len(nets), 1),
                "best_net": max(nets) if nets else 0.0,
                "avg_wr": sum(wrs) / len(wrs) if wrs else 0.0,
            }
        return out

    def summary_for_ai(self, *, limit: int = 24) -> str:
        lines = [f"Symbol {self.symbol} — recent search trials (newest last):"]
        for fam, st in sorted(self.family_stats().items(), key=lambda kv: kv[1]["best_net"], reverse=True):
            lines.append(
                f"  {fam}: {int(st['count'])} trials, best net ${st['best_net']:.0f}, "
                f"avg WR {st['avg_wr']:.0%}"
            )
        winners = [t for t in self.trials if t.outcome == "winner"][-5:]
        near = sorted(
            [t for t in self.trials if t.outcome in ("near_miss", "oos_fail", "train_reject")],
            key=lambda t: t.net,
            reverse=True,
        )[:limit]
        if winners:
            lines.append("Winners:")
            for t in winners:
                wr = f"{t.win_rate:.0%}" if t.win_rate is not None else "?"
                lines.append(f"  + {t.name} net=${t.net:.0f} WR={wr} PF={t.profit_factor}")
        if near:
            lines.append("Near-miss / rejects (mutate these toward ≥45% WR, PF≥1.1, intraday R:R):")
            for t in near[:12]:
                wr = f"{t.win_rate:.0%}" if t.win_rate is not None else "?"
                lines.append(f"  - {t.name} [{t.outcome}] net=${t.net:.0f} WR={wr} — {t.note}")
        return "\n".join(lines)

    def to_progress_blob(self) -> dict[str, Any]:
        return {
            "trials_recorded": len(self.trials),
            "family_stats": self.family_stats(),
            "winners": sum(1 for t in self.trials if t.outcome == "winner"),
        }