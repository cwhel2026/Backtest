"use client";

import { useEffect, useState } from "react";
import { StatCard } from "@/components/StatCard";
import { apiFetch } from "@/lib/api";

type OverviewStats = {
  instruments_count: number;
  strategies_total: number;
  strategies_validated: number;
  strategies_paper: number;
  strategies_rejected: number;
  active_research_jobs: number;
  queued_research_jobs: number;
  datasets_count: number;
  data_providers: { slug: string; display_name: string; state: string; message: string }[];
  ai_research_enabled: boolean;
  ai_configured: boolean;
};

type Activity = { id: string; headline: string; detail: string; created_at: string };

export default function OverviewPage() {
  const [stats, setStats] = useState<OverviewStats | null>(null);
  const [activity, setActivity] = useState<Activity[]>([]);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    Promise.all([
      apiFetch<OverviewStats>("/api/v1/overview/stats"),
      apiFetch<Activity[]>("/api/v1/research/activity?limit=12"),
    ])
      .then(([s, a]) => {
        setStats(s);
        setActivity(a);
      })
      .catch((e) => setError(String(e)));
  }, []);

  return (
    <div className="space-y-8">
      <header>
        <h2 className="page-title">Research overview</h2>
        <p className="page-sub">
          Live counts from PostgreSQL — no fabricated performance.
        </p>
      </header>

      {error ? <p className="text-sm text-red-400">{error}</p> : null}

      {stats ? (
        <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
          <StatCard label="Instruments" value={stats.instruments_count} hint="CME registry" />
          <StatCard label="Strategies" value={stats.strategies_total} />
          <StatCard label="Validated" value={stats.strategies_validated} />
          <StatCard label="Paper trading" value={stats.strategies_paper} />
          <StatCard label="Rejected" value={stats.strategies_rejected} />
          <StatCard label="Active jobs" value={stats.active_research_jobs} />
          <StatCard label="Queued jobs" value={stats.queued_research_jobs} />
          <StatCard label="Datasets" value={stats.datasets_count} hint="Imported historical data" />
        </div>
      ) : (
        <p className="text-zinc-500">Loading statistics…</p>
      )}

      {stats ? (
        <section className="rounded-lg border border-zinc-800 bg-[#181b22] p-6">
          <h3 className="text-sm font-medium text-zinc-300">Market data providers</h3>
          <ul className="mt-4 space-y-3">
            {stats.data_providers.map((p) => (
              <li key={p.slug} className="flex items-start justify-between gap-4 border-b border-zinc-800/80 pb-3 last:border-0">
                <div>
                  <p className="font-medium text-zinc-100">{p.display_name}</p>
                  <p className="text-sm text-zinc-500">{p.message}</p>
                </div>
                <span className="rounded-full bg-zinc-800 px-2 py-1 text-xs text-zinc-300">{p.state}</span>
              </li>
            ))}
          </ul>
          <p className="mt-4 text-xs text-zinc-500">
            AI research: {stats.ai_configured ? "configured" : "disabled"} (
            {stats.ai_research_enabled ? "enabled" : "flag off"})
          </p>
        </section>
      ) : null}

      <section className="rounded-lg border border-zinc-800 bg-[#181b22] p-6">
        <h3 className="text-sm font-medium text-zinc-300">Research activity feed</h3>
        <ul className="mt-4 space-y-4">
          {activity.length === 0 ? (
            <li className="text-sm text-zinc-500">No activity yet. Queue a data ingestion job from Market Data.</li>
          ) : (
            activity.map((a) => (
              <li key={a.id}>
                <p className="text-sm text-zinc-100">{a.headline}</p>
                {a.detail ? <p className="text-xs text-zinc-500">{a.detail}</p> : null}
              </li>
            ))
          )}
        </ul>
      </section>
    </div>
  );
}