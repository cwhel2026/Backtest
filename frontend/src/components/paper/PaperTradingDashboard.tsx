"use client";

import type { ReactNode } from "react";
import Link from "next/link";
import { useCallback, useEffect, useState } from "react";
import { Button } from "@/components/ui/Button";
import { EmptyState } from "@/components/ui/EmptyState";
import { PnlText } from "@/components/ui/PnlText";
import { apiFetch } from "@/lib/api";
import { latencyLabel } from "@/lib/navigation";

export type PaperRunCard = {
  id: string;
  strategy_name: string;
  symbol: string;
  timeframe: string;
  research_state: string;
  experimental: boolean;
  net_pnl: number;
  trade_count: number;
  max_drawdown: number;
  win_rate: number | null;
  last_signal_at: string | null;
  last_data_exchange_ts: string | null;
};

export function PaperTradingDashboard() {
  const [data, setData] = useState<Awaited<ReturnType<typeof loadPaper>> | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const load = useCallback(async () => {
    try {
      setData(await loadPaper());
      setErr(null);
    } catch (e) {
      setErr(e instanceof Error ? e.message : "Failed to load paper trading");
    }
  }, []);

  useEffect(() => {
    load();
    const t = setInterval(load, 20000);
    return () => clearInterval(t);
  }, [load]);

  async function tick() {
    setBusy(true);
    try {
      await apiFetch("/api/v1/live-lab/tick", { method: "POST" });
      await load();
    } finally {
      setBusy(false);
    }
  }

  const feed = data?.feed;
  const feedOk = feed && feed.connection_status === "connected" && !feed.is_paused;
  const latency = latencyLabel(feed?.latency_mode);

  return (
    <div className="space-y-5">
      {err ? (
        <p className="rounded-xl border border-red-500/40 bg-red-950/30 px-3 py-2 text-sm text-red-200">{err}</p>
      ) : null}

      <section className={`panel rounded-2xl border p-4 ${feedOk ? "border-[var(--profit)]/25" : "border-[var(--warning)]/40"}`}>
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div>
            <p className="metric-label">Market data</p>
            <p className="text-lg font-semibold text-zinc-50">{feed?.connection_status ?? "Unknown"}</p>
            <p className="mt-1 text-sm text-zinc-400">
              <span className="text-[var(--accent-teal)]">{latency}</span>
              {feed?.provider ? ` · ${feed.provider}` : ""}
            </p>
            <p className="mt-1 text-xs text-zinc-500">
              {latency.includes("Live") ? "" : "Not showing live exchange prices — simulation uses configured feed policy."}
            </p>
          </div>
          <div className="flex flex-col gap-2 sm:flex-row">
            <Link href="/paper-trading/certification">
              <Button variant="secondary">Certification</Button>
            </Link>
            <Button disabled={busy} onClick={tick}>
              Advance worker tick
            </Button>
          </div>
        </div>
      </section>

      <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
        <Metric label="Active runs" value={String(data?.active_strategy_count ?? "—")} />
        <Metric label="Paper equity" value={data ? `$${data.aggregate_equity.toLocaleString()}` : "—"} />
        <Metric
          label="Net simulated P&L"
          value={data ? <PnlText value={data.aggregate_net_pnl} /> : "—"}
        />
        <Metric label="Instruments" value="MNQ · MES · MGC" />
      </div>

      <section className="space-y-3">
        <h2 className="text-sm font-semibold text-zinc-200">Paper research runs</h2>
        {!data?.runs?.length ? (
          <EmptyState
            title="No paper runs yet"
            description="Pick a strategy in Strategy Lab, pass validation gates, then start forward paper research. Real money trading is never enabled here."
            actionHref="/strategy-lab"
            actionLabel="Open Strategy Lab"
          />
        ) : (
          data.runs.map((r) => (
            <Link
              key={r.id}
              href={`/paper-trading/${r.id}`}
              className="panel block rounded-2xl border border-[var(--border)] p-4 transition hover:border-[var(--accent)]/30"
            >
              <div className="flex items-start justify-between gap-2">
                <div>
                  <p className="font-medium text-zinc-50">{r.strategy_name}</p>
                  <p className="text-xs text-zinc-500">
                    {r.symbol} · {r.timeframe} · {r.research_state.replaceAll("_", " ")}
                    {r.experimental ? " · experimental" : ""}
                  </p>
                </div>
                <PnlText value={r.net_pnl} />
              </div>
              <p className="mt-2 text-xs text-zinc-500">
                {r.trade_count} closed trades · max DD ${r.max_drawdown.toFixed(0)}
                {r.win_rate != null ? ` · win ${(r.win_rate * 100).toFixed(0)}%` : ""}
              </p>
            </Link>
          ))
        )}
      </section>

      <p className="text-xs text-zinc-600">{data?.disclaimer}</p>
    </div>
  );
}

async function loadPaper() {
  return apiFetch<{
    feed: {
      provider: string | null;
      connection_status: string;
      latency_mode: string;
      last_heartbeat_at: string | null;
      is_paused: boolean;
    };
    active_strategy_count: number;
    aggregate_net_pnl: number;
    aggregate_equity: number;
    runs: PaperRunCard[];
    disclaimer: string;
  }>("/api/v1/live-lab/dashboard");
}

function Metric({ label, value }: { label: string; value: ReactNode }) {
  return (
    <div className="panel rounded-xl border border-[var(--border)] px-3 py-3">
      <p className="metric-label">{label}</p>
      <div className="mt-1 text-base font-semibold text-zinc-100">{value}</div>
    </div>
  );
}