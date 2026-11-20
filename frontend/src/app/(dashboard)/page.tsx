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

type Home = {
  summary: {
    markets_monitored: number;
    active_setups: number;
    setups_today: number;
    scanner_running: boolean;
    open_paper_runs: number;
    paper_trades_recorded: number;
    completed_setups: number;
    research_strategies_evaluated: number;
  };
  database_ok?: boolean;
  redis_ok?: boolean;
  workers_and_data?: { worker_name: string; stale: boolean }[];
  market_data_status: {
    latency_mode: string;
    connection_status: string;
    provider: string | null;
    platform_active: boolean;
    is_paused: boolean;
  };
  markets: {
    symbol: string;
    display_name: string;
    last_price: number | null;
    last_candle_ts: string | null;
    data_source: string | null;
    latency_mode: string;
  }[];
  latest_setups: {
    id: string;
    strategy: string;
    instrument: string;
    direction: string;
    entry: number | null;
    stop_loss: number | null;
    target: number | null;
    risk_reward: number | null;
    status: string;
    market_ts: string;
    explanation: string | null;
    feed_latency_mode: string | null;
  }[];
  paper_performance: {
    realised_net_pnl: number;
    open_equity: number;
    avg_win_rate: number | null;
    trade_count: number;
    disclaimer: string;
    runs: { id: string; strategy_name: string; symbol: string; net_pnl: number; trade_count: number }[];
  };
  recent_backtests: {
    id: string;
    strategy_name: string;
    instrument: string;
    status: string;
    period: string;
    trade_count?: number;
    net_pnl?: number;
    win_rate?: number;
    validation_status: string | null;
  }[];
};

export default function DashboardPage() {
  const [home, setHome] = useState<Home | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    apiFetch<Home>("/api/v1/dashboard/home")
      .then(setHome)
      .catch((e) => setError(String(e)))
      .finally(() => setLoading(false));
  }, []);

  const feedLatency = latencyLabel(home?.market_data_status?.latency_mode);
  const dataOk = home?.market_data_status?.platform_active;

  return (
    <div className="space-y-6 pb-10">
      <header>
        <h1 className="page-title">PROP EDGE AI</h1>
        <p className="page-sub">
          Live view of monitored micro futures, detected setups, and simulated paper performance —{" "}
          <span className="text-[var(--accent-teal)]">{feedLatency}</span> data, not live brokerage fills.
        </p>
      </header>

      {error ? <Card className="border-red-900/40 text-sm text-red-200">{error}</Card> : null}

      {loading ? (
        <LoadingGrid />
      ) : (
        <>
          <section className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
            <DashMetric label="Markets monitored" value={String(home?.summary.markets_monitored ?? 0)} href="/scanner" />
            <DashMetric label="Active setups" value={String(home?.summary.active_setups ?? 0)} href="/scanner" />
            <DashMetric label="Open paper runs" value={String(home?.summary.open_paper_runs ?? 0)} href="/paper-trading" />
            <DashMetric
              label="Completed paper outcomes"
              value={String(home?.summary.completed_setups ?? 0)}
              href="/paper-trading"
            />
            <DashMetric
              label="Simulated trades (runs)"
              value={String(home?.summary.paper_trades_recorded ?? 0)}
              href="/paper-trading"
            />
            <DashMetric label="Recent backtests" value={String(home?.recent_backtests.length ?? 0)} href="/backtests" />
          </section>

          <Card className="panel space-y-2">
            <h2 className="text-sm font-semibold text-zinc-200">Platform health</h2>
            <p className="text-sm text-zinc-400">
              Provider {home?.market_data_status.provider ?? "—"} · {feedLatency} ·{" "}
              {home?.market_data_status.connection_status ?? "—"}
            </p>
            <p className="text-sm text-zinc-400">
              Scanner {home?.summary.scanner_running ? "running" : "stopped or stale"} · Setups today{" "}
              {home?.summary.setups_today ?? 0}
            </p>
            <p className="text-xs text-zinc-500">
              Database {home?.database_ok ? "OK" : "issue"} · Redis {home?.redis_ok ? "OK" : "not checked"}
            </p>
            {!dataOk ? (
              <p className="text-xs text-amber-200/90">
                Ingestion or worker heartbeat may be stale — Celery beat must run health_pulse and live_lab_forward_tick.
              </p>
            ) : null}
          </Card>

          <section className="space-y-3">
            <h2 className="text-sm font-semibold text-zinc-200">Market overview</h2>
            <div className="grid gap-3 sm:grid-cols-3">
              {home?.markets.map((m) => (
                <Card key={m.symbol} className="panel space-y-1">
                  <p className="text-lg font-semibold text-zinc-50">{m.symbol}</p>
                  <p className="text-xs text-zinc-500">{m.display_name}</p>
                  <p className="text-xl tabular-nums text-zinc-100">
                    {m.last_price != null ? m.last_price.toLocaleString(undefined, { maximumFractionDigits: 2 }) : "—"}
                  </p>
                  <p className="text-xs text-zinc-500">
                    {m.last_candle_ts ? new Date(m.last_candle_ts).toLocaleString() : "No stored candles"}
                  </p>
                  <p className="text-xs text-zinc-600">Source: {m.data_source ?? "—"}</p>
                </Card>
              ))}
            </div>
          </section>

          <section className="space-y-3">
            <div className="flex items-center justify-between">
              <h2 className="text-sm font-semibold text-zinc-200">Latest setups</h2>
              <Link href="/scanner" className="text-xs text-[var(--accent)]">
                Full scanner
              </Link>
            </div>
            {home?.latest_setups?.length ? (
              <ul className="space-y-2">
                {home.latest_setups.slice(0, 8).map((s) => (
                  <li key={s.id}>
                    <Link href={`/scanner/${s.id}`}>
                      <Card className="flex flex-wrap items-center justify-between gap-2 py-3">
                        <span className="text-sm text-zinc-200">
                          {s.strategy} · {s.instrument} · {s.direction.toUpperCase()}
                        </span>
                        <span className="text-xs text-zinc-500">{s.status.replaceAll("_", " ")}</span>
                        <span className="text-xs tabular-nums text-zinc-400">
                          Entry {s.entry ?? "—"} · R:R {s.risk_reward ?? "—"}
                        </span>
                      </Card>
                    </Link>
                  </li>
                ))}
              </ul>
            ) : (
              <EmptyState
                title="No setups stored yet"
                description="Run market-data replay or forward paper tests. Setups appear when incremental engines detect qualifying structure on a closed bar."
                actionHref="/scanner"
                actionLabel="Open scanner"
              />
            )}
          </section>

          <div className="grid gap-4 lg:grid-cols-2">
            <Card className="panel space-y-3">
              <h2 className="text-sm font-semibold text-zinc-200">Paper performance (simulated)</h2>
              <p className="text-3xl font-semibold tabular-nums">
                <PnlText value={home?.paper_performance.realised_net_pnl ?? 0} className="text-3xl" />
              </p>
              <p className="text-sm text-zinc-500">
                Trades recorded: {home?.paper_performance.trade_count ?? 0}
                {home?.paper_performance.avg_win_rate != null
                  ? ` · Win rate ${(home.paper_performance.avg_win_rate * 100).toFixed(1)}%`
                  : ""}
              </p>
              <p className="text-xs text-zinc-600">{home?.paper_performance.disclaimer}</p>
              <Link href="/paper-trading">
                <Button variant="secondary">Paper Trading</Button>
              </Link>
            </Card>

            <Card className="panel space-y-3">
              <h2 className="text-sm font-semibold text-zinc-200">Recent backtests</h2>
              {home?.recent_backtests?.length ? (
                <ul className="space-y-2">
                  {home.recent_backtests.slice(0, 4).map((r) => (
                    <li key={r.id}>
                      <Link href={`/backtests/${r.id}`}>
                        <div className="flex items-center justify-between border-b border-[var(--border)]/40 py-2 text-sm">
                          <span className="text-zinc-200">
                            {r.strategy_name} · {r.instrument}
                          </span>
                          {r.net_pnl != null ? <PnlText value={r.net_pnl} /> : <span className="text-zinc-500">{r.status}</span>}
                        </div>
                        <p className="text-xs text-zinc-500">
                          {r.period}
                          {r.trade_count != null ? ` · ${r.trade_count} trades` : ""}
                          {r.validation_status ? ` · ${r.validation_status.replaceAll("_", " ")}` : ""}
                        </p>
                      </Link>
                    </li>
                  ))}
                </ul>
              ) : (
                <p className="text-sm text-zinc-500">No backtests yet.</p>
              )}
              <Link href="/backtests/run">
                <Button variant="secondary">Run backtest</Button>
              </Link>
            </Card>
          </div>
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
    <div className="grid grid-cols-2 gap-3 lg:grid-cols-3">
      {[1, 2, 3, 4, 5, 6].map((i) => (
        <Skeleton key={i} className="h-20" />
      ))}
    </div>
  );
}