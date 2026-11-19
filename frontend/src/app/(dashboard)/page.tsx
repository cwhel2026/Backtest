"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { LeaderboardCard, type LeaderboardEntry } from "@/components/LeaderboardCard";
import { Card } from "@/components/ui/Card";
import { Button } from "@/components/ui/Button";
import { Skeleton } from "@/components/ui/Skeleton";
import { apiFetch } from "@/lib/api";

type Overview = {
  strategies_total: number;
  strategies_validated: number;
  active_research_jobs: number;
  queued_research_jobs: number;
  datasets_count: number;
  genuine_datasets_count: number;
  backtests_completed_count: number;
  ai_research_enabled: boolean;
  ai_configured: boolean;
  data_providers: { slug: string; state: string; message: string }[];
};

type BacktestRun = {
  id: string;
  status: string;
  created_at: string;
  completed_at: string | null;
  metrics: { net_profit_usd?: number; trade_count?: number } | null;
};

function StatusPill({ ok, label }: { ok: boolean; label: string }) {
  return (
    <span
      className={`inline-flex items-center rounded-full px-2.5 py-1 text-xs font-medium ${
        ok ? "bg-emerald-500/15 text-emerald-300" : "bg-amber-500/15 text-amber-200"
      }`}
    >
      {label}
    </span>
  );
}

export default function HomePage() {
  const [overview, setOverview] = useState<Overview | null>(null);
  const [recentRuns, setRecentRuns] = useState<BacktestRun[]>([]);
  const [topValidated, setTopValidated] = useState<LeaderboardEntry[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    Promise.all([
      apiFetch<Overview>("/api/v1/overview/stats"),
      apiFetch<BacktestRun[]>("/api/v1/backtests"),
      apiFetch<LeaderboardEntry[]>("/api/v1/autopilot/leaderboard?profitable_only=true&limit=5"),
    ])
      .then(([o, runs, board]) => {
        setOverview(o);
        setRecentRuns(runs.slice(0, 6));
        setTopValidated(board);
      })
      .catch((e) => setError(String(e)))
      .finally(() => setLoading(false));
  }, []);

  const engineOk = overview
    ? overview.data_providers.every(
        (p) =>
          p.state === "connected" ||
          p.state === "configured" ||
          p.state === "not_configured" ||
          p.state === "healthy",
      )
    : false;
  const researchActive = (overview?.active_research_jobs ?? 0) + (overview?.queued_research_jobs ?? 0) > 0;
  const needsGenuineData = overview != null && overview.genuine_datasets_count === 0;

  return (
    <div className="space-y-6">
      <header>
        <h1 className="page-title">Research overview</h1>
        <p className="page-sub">Status of strategies, data, backtests, and AI jobs — at a glance on mobile.</p>
      </header>

      {error ? (
        <Card className="border-red-900/50 bg-red-950/30 text-sm text-red-200">{error}</Card>
      ) : null}

      {loading ? (
        <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
          {[1, 2, 3, 4].map((i) => (
            <Skeleton key={i} className="h-24" />
          ))}
        </div>
      ) : overview ? (
        <>
          <Card className="space-y-3">
            <div className="flex flex-wrap items-center gap-2">
              <StatusPill ok={engineOk} label={engineOk ? "Platform online" : "Data provider issue"} />
              <StatusPill ok={!researchActive || true} label={researchActive ? "AI / jobs running" : "No queued jobs"} />
              {overview.ai_configured ? (
                <StatusPill ok label="OpenAI configured" />
              ) : overview.ai_research_enabled ? (
                <StatusPill ok={false} label="Add OPENAI_API_KEY" />
              ) : (
                <StatusPill ok label="Heuristic research mode" />
              )}
            </div>
            <p className="text-sm text-zinc-400">
              {overview.backtests_completed_count} completed backtests · {overview.genuine_datasets_count} genuine
              datasets · {overview.strategies_validated} validated strategies
            </p>
          </Card>

          <MetricTiles overview={overview} />

          {needsGenuineData ? (
            <Card className="border-[var(--accent)]/30 bg-[var(--accent-muted)]">
              <h2 className="text-base font-semibold text-zinc-100">Start with licensed history</h2>
              <p className="mt-2 text-sm text-zinc-300">
                No dataset is marked <strong className="font-medium text-zinc-100">genuine for research</strong> yet.
                Import Databento or approved CSV on Market Data before trusting backtest P&amp;L.
              </p>
              <Link href="/market-data" className="mt-4 inline-block">
                <Button variant="primary">Open Market Data</Button>
              </Link>
            </Card>
          ) : null}

          <section className="space-y-3">
            <SectionTitle title="Quick actions" />
            <div className="grid gap-3 sm:grid-cols-2">
              <Link href="/backtests/run">
                <Card className="hover:border-[var(--accent)]/40">
                  <p className="font-semibold text-zinc-100">Run a backtest</p>
                  <p className="mt-1 text-sm text-zinc-400">Guided 5-step flow — strategy, market, dataset, risk, run.</p>
                </Card>
              </Link>
              <Link href="/research">
                <Card className="hover:border-[var(--accent)]/40">
                  <p className="font-semibold text-zinc-100">AI research</p>
                  <p className="mt-1 text-sm text-zinc-400">Monitor jobs and queue new strategy experiments.</p>
                </Card>
              </Link>
            </div>
          </section>

          <section className="space-y-3">
            <SectionTitle title="Recent backtests" />
            {recentRuns.length === 0 ? (
              <p className="text-sm text-zinc-500">No backtests yet.</p>
            ) : (
              <ul className="space-y-2">
                {recentRuns.map((r) => (
                  <li key={r.id}>
                    <Link href={`/backtests/${r.id}`}>
                      <Card className="flex items-center justify-between gap-3 py-3">
                        <p className="text-sm text-zinc-300">
                          <span className="font-mono text-xs text-zinc-500">{r.id.slice(0, 8)}</span> · {r.status}
                        </p>
                        {r.metrics?.net_profit_usd != null ? (
                          <span className="text-sm tabular-nums text-zinc-200">
                            ${r.metrics.net_profit_usd.toFixed(0)}
                          </span>
                        ) : null}
                      </Card>
                    </Link>
                  </li>
                ))}
              </ul>
            )}
          </section>

          <section className="space-y-3">
            <SectionTitle title="Top validated (genuine screen)" />
            {topValidated.length === 0 ? (
              <p className="text-sm text-zinc-500">No keeper-grade results yet — run search or backtests on licensed data.</p>
            ) : (
              <ul className="space-y-4">
                {topValidated.map((row) => (
                  <LeaderboardCard key={row.run_id} row={row} />
                ))}
              </ul>
            )}
            <Link href="/leaderboard" className="text-sm font-medium text-[var(--accent)]">
              Full leaderboard →
            </Link>
          </section>
        </>
      ) : null}
    </div>
  );
}

function MetricTiles({ overview }: { overview: Overview }) {
  const tiles = [
    { label: "Strategies", value: String(overview.strategies_total) },
    { label: "Validated", value: String(overview.strategies_validated) },
    { label: "Genuine data", value: String(overview.genuine_datasets_count) },
    { label: "Backtests done", value: String(overview.backtests_completed_count) },
  ];
  return (
    <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
      {tiles.map((t) => (
        <Card key={t.label} className="py-3">
          <p className="metric-label">{t.label}</p>
          <p className="metric-value">{t.value}</p>
        </Card>
      ))}
    </div>
  );
}

function SectionTitle({ title }: { title: string }) {
  return <h2 className="text-sm font-semibold uppercase tracking-wide text-zinc-500">{title}</h2>;
}