"use client";

import { useParams } from "next/navigation";
import { useCallback, useEffect, useState } from "react";
import { Card } from "@/components/ui/Card";
import { apiFetch } from "@/lib/api";

type ResearcherDetail = {
  researcher: {
    display_name: string;
    current_activity: string;
    latest_hypothesis: string | null;
    enabled: boolean;
    daily_budget_usd: number;
    monthly_budget_usd: number;
    remaining_daily_budget_usd: number;
    remaining_monthly_budget_usd: number;
    max_refinement_depth: number;
    max_child_experiments: number;
    max_backtests_per_cycle: number;
  };
  forward_paper: Record<string, unknown>;
  cycles: { id: string; status: string; phase: string; started_at: string }[];
  evolution_tree: {
    id: string;
    parent_id: string | null;
    status: string;
    tier: string;
    family: string;
    hypothesis: string;
    metrics: Record<string, unknown>;
  }[];
  experiments: {
    id: string;
    parent_experiment_id: string | null;
    status: string;
    validation_tier: string;
    hypothesis: string;
    rejection_reason: string | null;
    metrics: Record<string, unknown>;
    lineage: Record<string, unknown>;
  }[];
};

export default function ResearcherPage() {
  const params = useParams();
  const slug = String(params.slug);
  const [data, setData] = useState<ResearcherDetail | null>(null);

  const refresh = useCallback(() => {
    return apiFetch<ResearcherDetail>(`/api/v1/ai-arena/researchers/${slug}`).then(setData);
  }, [slug]);

  useEffect(() => {
    refresh().catch(() => setData(null));
  }, [refresh]);

  async function action(path: string) {
    await apiFetch(`/api/v1/ai-arena/researchers/${slug}${path}`, { method: "POST" });
    await refresh();
  }

  if (!data) return <p className="text-zinc-500">Loading…</p>;

  const r = data.researcher;
  const fp = data.forward_paper;

  return (
    <div className="space-y-4 pb-10">
      <header className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h1 className="page-title">{r.display_name}</h1>
          <p className="text-sm text-zinc-400">{r.current_activity}</p>
          <p className="mt-2 text-sm text-zinc-300">{r.latest_hypothesis || "No hypothesis yet"}</p>
        </div>
        <div className="flex flex-wrap gap-2">
          <button type="button" className="rounded border border-zinc-700 px-2 py-1 text-xs" onClick={() => action("/test-connection")}>
            Test connection
          </button>
          <button type="button" className="rounded border border-zinc-700 px-2 py-1 text-xs" onClick={() => action("/start")}>
            Start
          </button>
          <button type="button" className="rounded border border-zinc-700 px-2 py-1 text-xs" onClick={() => action("/stop")}>
            Stop
          </button>
          <button type="button" className="rounded border border-zinc-700 px-2 py-1 text-xs" onClick={() => action("/run-cycle")}>
            Run research now
          </button>
        </div>
      </header>

      <Card className="panel text-sm text-zinc-400">
        API budget remaining: ${r.remaining_daily_budget_usd.toFixed(2)} today · $
        {r.remaining_monthly_budget_usd.toFixed(2)} this month. Refinement limits: depth {r.max_refinement_depth}, children{" "}
        {r.max_child_experiments}, backtests/cycle {r.max_backtests_per_cycle}.
      </Card>

      <Card className="panel space-y-2 text-sm">
        <h2 className="font-semibold text-zinc-200">Forward paper (separate from backtest)</h2>
        <p className="text-zinc-400">
          Active {String(fp.active_forward_strategies ?? 0)} · Closed trades {String(fp.closed_paper_trades ?? 0)} · Net P&L $
          {Number(fp.paper_net_pnl ?? 0).toFixed(2)}
          {fp.insufficient_sample ? " (insufficient sample for ranking)" : ""}
        </p>
      </Card>

      <Card className="panel space-y-2">
        <h2 className="text-sm font-semibold text-zinc-200">Strategy evolution tree</h2>
        {data.evolution_tree.length === 0 ? (
          <p className="text-xs text-zinc-500">No experiments yet.</p>
        ) : (
          <ul className="space-y-2 text-xs text-zinc-400">
            {data.evolution_tree.map((node) => (
              <li key={node.id} className="border-l-2 border-zinc-700 pl-2" style={{ marginLeft: node.parent_id ? 12 : 0 }}>
                <span className="text-zinc-200">
                  {node.tier} · {node.family}
                </span>
                {node.parent_id ? <span className="text-zinc-600"> ← parent {node.parent_id.slice(0, 8)}</span> : null}
                <p>{node.hypothesis}</p>
                {node.metrics?.net_pnl != null ? (
                  <p>
                    Backtest net ${String(node.metrics.net_pnl)} · trades {String(node.metrics.trade_count)}
                  </p>
                ) : null}
              </li>
            ))}
          </ul>
        )}
      </Card>

      <Card className="panel space-y-3">
        <h2 className="text-sm font-semibold text-zinc-200">Recent cycles</h2>
        {data.cycles.map((c) => (
          <p key={c.id} className="text-xs text-zinc-500">
            {c.status} · {c.phase} · {c.started_at}
          </p>
        ))}
      </Card>
    </div>
  );
}