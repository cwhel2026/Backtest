"use client";

import Link from "next/link";
import { useCallback, useEffect, useState } from "react";
import { Card } from "@/components/ui/Card";
import { EmptyState } from "@/components/ui/EmptyState";
import { Skeleton } from "@/components/ui/Skeleton";
import { apiFetch } from "@/lib/api";

type Researcher = {
  id: string;
  provider_slug: string;
  display_name: string;
  enabled: boolean;
  activated_by_user: boolean;
  connection_status: string;
  model_id: string;
  current_activity: string;
  last_cycle_at: string | null;
  stats: Record<string, number>;
  daily_spend_usd: number;
  monthly_spend_usd: number;
  daily_budget_usd: number;
  monthly_budget_usd: number;
  research_frequency_minutes: number;
  experiments_by_status: Record<string, number>;
};

type LeaderRow = {
  provider_slug: string;
  display_name: string;
  validated: number;
  failed: number;
  unique_tested: number;
  composite_score: number;
  monthly_research_cost_usd: number;
  cost_per_validated_strategy_usd: number | null;
};

type Arena = {
  researchers: Researcher[];
  leaderboard: LeaderRow[];
  global: {
    emergency_stop: boolean;
    global_daily_budget_usd: number;
    global_monthly_budget_usd: number;
    global_daily_spend_usd: number;
    global_monthly_spend_usd: number;
    auto_paper_promotion: boolean;
  };
  provider_catalog: { slug: string; env_var: string; key_configured: boolean; default_model: string }[];
};

export default function AiArenaPage() {
  const [arena, setArena] = useState<Arena | null>(null);
  const [loading, setLoading] = useState(true);

  const refresh = useCallback(() => {
    return apiFetch<Arena>("/api/v1/ai-arena").then(setArena);
  }, []);

  useEffect(() => {
    refresh()
      .catch(() => setArena(null))
      .finally(() => setLoading(false));
  }, [refresh]);

  async function patchGlobal(body: Record<string, unknown>) {
    await apiFetch("/api/v1/ai-arena/global", { method: "PATCH", body: JSON.stringify(body) });
    await refresh();
  }

  async function patchResearcher(slug: string, body: Record<string, unknown>) {
    await apiFetch(`/api/v1/ai-arena/researchers/${slug}/settings`, {
      method: "PATCH",
      body: JSON.stringify(body),
    });
    await refresh();
  }

  async function testConnection(slug: string) {
    await apiFetch(`/api/v1/ai-arena/researchers/${slug}/test-connection`, { method: "POST" });
    await refresh();
  }

  async function runCycle(slug: string) {
    await apiFetch(`/api/v1/ai-arena/researchers/${slug}/run-cycle`, { method: "POST" });
    await refresh();
  }

  async function startResearcher(slug: string) {
    await apiFetch(`/api/v1/ai-arena/researchers/${slug}/start`, { method: "POST" });
    await refresh();
  }

  async function stopResearcher(slug: string) {
    await apiFetch(`/api/v1/ai-arena/researchers/${slug}/stop`, { method: "POST" });
    await refresh();
  }

  return (
    <div className="space-y-6 pb-10">
      <header>
        <h1 className="page-title">AI Research Arena</h1>
        <p className="page-sub">
          Eight independent LLM researchers under research-grade validation — simulated paper only, no live orders.
        </p>
      </header>

      {loading ? (
        <Skeleton className="h-40 w-full" />
      ) : !arena ? (
        <EmptyState title="Arena unavailable" description="Check login and API health." />
      ) : (
        <>
          <Card className="panel space-y-3 text-sm">
            <h2 className="font-semibold text-zinc-200">Global controls</h2>
            <p className="text-zinc-500">
              Spend today ${arena.global.global_daily_spend_usd.toFixed(3)} / $
              {arena.global.global_daily_budget_usd.toFixed(2)} · Month $
              {arena.global.global_monthly_spend_usd.toFixed(2)} / ${arena.global.global_monthly_budget_usd.toFixed(2)}
            </p>
            <div className="flex flex-wrap gap-2">
              <button
                type="button"
                className="rounded-md border border-red-800 px-3 py-1.5 text-xs text-red-200 hover:bg-red-950"
                onClick={() => patchGlobal({ emergency_stop: !arena.global.emergency_stop })}
              >
                {arena.global.emergency_stop ? "Release emergency stop" : "Emergency stop all researchers"}
              </button>
              <button
                type="button"
                className="rounded-md border border-zinc-700 px-3 py-1.5 text-xs text-zinc-200 hover:bg-zinc-800"
                onClick={() => patchGlobal({ auto_paper_promotion: !arena.global.auto_paper_promotion })}
              >
                Paper auto-promotion: {arena.global.auto_paper_promotion ? "On" : "Off"}
              </button>
            </div>
          </Card>

          <section className="grid gap-3 lg:grid-cols-2">
            {arena.researchers.map((r) => (
              <Card key={r.id} className="panel space-y-2">
                <div className="flex items-start justify-between gap-2">
                  <Link href={`/ai-arena/${r.provider_slug}`} className="font-medium text-[var(--accent-teal)]">
                    {r.display_name}
                  </Link>
                  <span className="text-xs text-zinc-500">{r.connection_status}</span>
                </div>
                <p className="text-sm text-zinc-300">{r.current_activity || "Idle"}</p>
                <label className="block text-xs text-zinc-500">
                  Model
                  <input
                    className="mt-1 w-full rounded border border-zinc-700 bg-zinc-900 px-2 py-1 text-zinc-200"
                    defaultValue={r.model_id}
                    onBlur={(e) => patchResearcher(r.provider_slug, { model_id: e.target.value })}
                  />
                </label>
                <div className="grid grid-cols-2 gap-2 text-xs">
                  <label>
                    Daily budget $
                    <input
                      type="number"
                      className="mt-1 w-full rounded border border-zinc-700 bg-zinc-900 px-2 py-1"
                      defaultValue={r.daily_budget_usd}
                      onBlur={(e) => patchResearcher(r.provider_slug, { daily_budget_usd: Number(e.target.value) })}
                    />
                  </label>
                  <label>
                    Monthly budget $
                    <input
                      type="number"
                      className="mt-1 w-full rounded border border-zinc-700 bg-zinc-900 px-2 py-1"
                      defaultValue={r.monthly_budget_usd}
                      onBlur={(e) => patchResearcher(r.provider_slug, { monthly_budget_usd: Number(e.target.value) })}
                    />
                  </label>
                </div>
                <label className="block text-xs text-zinc-500">
                  Research frequency (minutes)
                  <input
                    type="number"
                    className="mt-1 w-full rounded border border-zinc-700 bg-zinc-900 px-2 py-1"
                    defaultValue={r.research_frequency_minutes}
                    onBlur={(e) =>
                      patchResearcher(r.provider_slug, { research_frequency_minutes: Number(e.target.value) })
                    }
                  />
                </label>
                <p className="text-xs text-zinc-500">
                  Validated {r.experiments_by_status?.validated ?? 0} · Experimental{" "}
                  {r.experiments_by_status?.experimental ?? 0} · Rejected{" "}
                  {(r.experiments_by_status?.rejected ?? 0) + (r.experiments_by_status?.duplicate ?? 0)}
                </p>
                <p className="text-xs text-zinc-500">
                  Spend ${r.daily_spend_usd.toFixed(3)} today · ${r.monthly_spend_usd.toFixed(2)} month
                </p>
                <div className="flex flex-wrap gap-2">
                  <button
                    type="button"
                    className="rounded-md border border-zinc-700 px-2 py-1 text-xs"
                    onClick={() => testConnection(r.provider_slug)}
                  >
                    Test connection
                  </button>
                  <button type="button" className="rounded-md border border-zinc-700 px-2 py-1 text-xs" onClick={() => startResearcher(r.provider_slug)}>
                    Start
                  </button>
                  <button type="button" className="rounded-md border border-zinc-700 px-2 py-1 text-xs" onClick={() => stopResearcher(r.provider_slug)}>
                    Stop
                  </button>
                  <button
                    type="button"
                    className="rounded-md border border-zinc-700 px-2 py-1 text-xs"
                    onClick={() => runCycle(r.provider_slug)}
                  >
                    Run research now
                  </button>
                </div>
              </Card>
            ))}
          </section>

          <Card className="panel">
            <h2 className="mb-3 text-sm font-semibold text-zinc-200">Researcher leaderboard (composite score)</h2>
            <ul className="space-y-2 text-sm">
              {arena.leaderboard.length === 0 ? (
                <li className="text-zinc-500">No research activity yet.</li>
              ) : (
                arena.leaderboard.map((row) => (
                  <li key={row.provider_slug} className="flex flex-wrap justify-between gap-2 text-zinc-300">
                    <span>
                      {row.display_name} · {row.validated} validated · {row.unique_tested} unique · {row.failed} failed
                    </span>
                    <span className="font-mono text-zinc-400">
                      score {row.composite_score} · ${row.monthly_research_cost_usd.toFixed(2)} research
                    </span>
                  </li>
                ))
              )}
            </ul>
          </Card>
        </>
      )}
    </div>
  );
}