"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { Button } from "@/components/ui/Button";
import { Card } from "@/components/ui/Card";
import { EmptyState } from "@/components/ui/EmptyState";
import { PnlText } from "@/components/ui/PnlText";
import { Skeleton } from "@/components/ui/Skeleton";
import { apiFetch } from "@/lib/api";
import { latencyLabel } from "@/lib/navigation";

type Overview = {
  strategies_total: number;
  strategies_validated: number;
  strategies_paper: number;
  active_research_jobs: number;
  queued_research_jobs: number;
  genuine_datasets_count: number;
  backtests_completed_count: number;
  ai_research_enabled: boolean;
  ai_configured: boolean;
  data_providers: { slug: string; state: string; message: string }[];
};

type PaperDash = {
  active_strategy_count: number;
  aggregate_net_pnl: number;
  aggregate_equity: number;
  feed: { connection_status: string; latency_mode: string; provider: string | null; is_paused: boolean };
  runs: {
    id: string;
    strategy_name: string;
    symbol: string;
    net_pnl: number;
    trade_count: number;
    research_state: string;
  }[];
};

type BacktestRun = {
  id: string;
  status: string;
  metrics: { net_profit_usd?: number; trade_count?: number; win_rate?: number; profit_factor?: number } | null;
};

export default function DashboardPage() {
  const [overview, setOverview] = useState<Overview | null>(null);
  const [paper, setPaper] = useState<PaperDash | null>(null);
  const [backtests, setBacktests] = useState<BacktestRun[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    Promise.all([
      apiFetch<Overview>("/api/v1/overview/stats"),
      apiFetch<PaperDash>("/api/v1/live-lab/dashboard"),
      apiFetch<BacktestRun[]>("/api/v1/backtests"),
    ])
      .then(([o, p, bt]) => {
        setOverview(o);
        setPaper(p);
        setBacktests(bt.filter((r) => r.status === "completed").slice(0, 5));
      })
      .catch((e) => setError(String(e)))
      .finally(() => setLoading(false));
  }, []);

  const feedLatency = latencyLabel(paper?.feed?.latency_mode);
  const workersOk = paper?.feed && !paper.feed.is_paused;

  return (
    <div className="space-y-6">
      <header>
        <h1 className="page-title">Dashboard</h1>
        <p className="page-sub">What the platform is monitoring, simulating, and researching — from live API data.</p>
      </header>

      {error ? <Card className="border-red-900/40 text-sm text-red-200">{error}</Card> : null}

      {loading ? (
        <LoadingGrid />
      ) : (
        <>
          <section className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
            <DashMetric label="Strategies in library" value={String(overview?.strategies_total ?? 0)} href="/strategy-lab" />
            <DashMetric
              label="Historically validated"
              value={String(overview?.strategies_validated ?? 0)}
              href="/analytics"
            />
            <DashMetric label="Paper runs active" value={String(paper?.active_strategy_count ?? 0)} href="/paper-trading" />
            <DashMetric
              label="Completed backtests"
              value={String(overview?.backtests_completed_count ?? 0)}
              href="/backtests"
            />
          </section>

          <div className="grid gap-4 lg:grid-cols-2">
            <Card className="panel space-y-3">
              <h2 className="text-sm font-semibold text-zinc-200">Market data & worker</h2>
              <p className="text-sm text-zinc-400">
                Connection: <span className="text-zinc-100">{paper?.feed.connection_status ?? "—"}</span>
              </p>
              <p className="text-sm text-zinc-400">
                Latency class: <span className="text-[var(--accent-teal)]">{feedLatency}</span>
                {paper?.feed.provider ? ` · ${paper.feed.provider}` : ""}
              </p>
              {!workersOk ? (
                <p className="text-xs text-amber-200/90">Feed paused or disconnected — new paper signals may be withheld.</p>
              ) : (
                <p className="text-xs text-zinc-500">Worker tick processes closed bars and paper ledger events.</p>
              )}
              <Link href="/scanner">
                <Button variant="secondary">Open Market Scanner</Button>
              </Link>
            </Card>

            <Card className="panel space-y-3">
              <h2 className="text-sm font-semibold text-zinc-200">Simulated paper P&amp;L</h2>
              <p className="text-3xl font-semibold tabular-nums">
                {paper ? <PnlText value={paper.aggregate_net_pnl} className="text-3xl" /> : "—"}
              </p>
              <p className="text-sm text-zinc-500">Equity across runs: ${paper?.aggregate_equity.toLocaleString() ?? "—"}</p>
              <Link href="/paper-trading">
                <Button variant="secondary">Paper Trading</Button>
              </Link>
            </Card>
          </div>

          {overview?.genuine_datasets_count === 0 ? (
            <EmptyState
              title="Import licensed history first"
              description="Backtests on unverified data are blocked or flagged. Use Settings → Historical data to import Databento or approved CSV."
              actionHref="/settings"
              actionLabel="Open Settings"
            />
          ) : null}

          <section className="space-y-3">
            <div className="flex items-center justify-between">
              <h2 className="text-sm font-semibold text-zinc-200">Active paper &amp; recent signals</h2>
              <Link href="/paper-trading" className="text-xs text-[var(--accent)]">
                View all
              </Link>
            </div>
            {paper?.runs?.length ? (
              <ul className="space-y-2">
                {paper.runs.slice(0, 6).map((r) => (
                  <li key={r.id}>
                    <Link href={`/paper-trading/${r.id}`}>
                      <Card className="flex items-center justify-between gap-2 py-3">
                        <span className="text-sm text-zinc-200">
                          {r.strategy_name} · {r.symbol}
                        </span>
                        <PnlText value={r.net_pnl} />
                      </Card>
                    </Link>
                  </li>
                ))}
              </ul>
            ) : (
              <p className="text-sm text-zinc-500">No forward paper runs yet.</p>
            )}
          </section>

          <section className="space-y-3">
            <div className="flex items-center justify-between">
              <h2 className="text-sm font-semibold text-zinc-200">Recent backtests</h2>
              <Link href="/backtests/run" className="text-xs text-[var(--accent)]">
                New backtest
              </Link>
            </div>
            {backtests.length === 0 ? (
              <p className="text-sm text-zinc-500">No completed backtests yet.</p>
            ) : (
              <ul className="space-y-2">
                {backtests.map((r) => (
                  <li key={r.id}>
                    <Link href={`/backtests/${r.id}`}>
                      <Card className="flex items-center justify-between py-3">
                        <span className="text-sm text-zinc-300">Backtest complete</span>
                        {r.metrics?.net_profit_usd != null ? (
                          <PnlText value={r.metrics.net_profit_usd} />
                        ) : (
                          <span className="text-xs text-zinc-500">View report</span>
                        )}
                      </Card>
                    </Link>
                  </li>
                ))}
              </ul>
            )}
          </section>

          <section className="flex flex-wrap gap-3">
            <Link href="/research">
              <Button variant="secondary">
                AI Research
                {(overview?.active_research_jobs ?? 0) + (overview?.queued_research_jobs ?? 0) > 0
                  ? ` (${(overview?.active_research_jobs ?? 0) + (overview?.queued_research_jobs ?? 0)} jobs)`
                  : ""}
              </Button>
            </Link>
            <Link href="/backtests/run">
              <Button>Run backtest wizard</Button>
            </Link>
          </section>
        </>
      )}
    </div>
  );
}

function DashMetric({ label, value, href }: { label: string; value: string; href: string }) {
  return (
    <Link href={href}>
      <Card className="panel hover:border-[var(--accent)]/25">
        <p className="metric-label">{label}</p>
        <p className="metric-value">{value}</p>
      </Card>
    </Link>
  );
}

function LoadingGrid() {
  return (
    <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
      {[1, 2, 3, 4].map((i) => (
        <Skeleton key={i} className="h-20" />
      ))}
    </div>
  );
}