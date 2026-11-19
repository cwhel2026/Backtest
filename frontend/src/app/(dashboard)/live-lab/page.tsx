"use client";

import Link from "next/link";
import { useCallback, useEffect, useState } from "react";

import { Button } from "@/components/ui/Button";
import { apiFetch } from "@/lib/api";

type RunCard = {
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

type Dashboard = {
  feed: {
    provider: string | null;
    connection_status: string;
    latency_mode: string;
    last_heartbeat_at: string | null;
    is_paused: boolean;
    incidents: { kind: string; detail?: string }[];
  };
  active_strategy_count: number;
  aggregate_net_pnl: number;
  aggregate_equity: number;
  runs: RunCard[];
  disclaimer: string;
};

export default function LiveStrategyLabPage() {
  const [data, setData] = useState<Dashboard | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const load = useCallback(async () => {
    try {
      const d = await apiFetch<Dashboard>("/api/v1/live-lab/dashboard");
      setData(d);
      setErr(null);
    } catch (e) {
      setErr(e instanceof Error ? e.message : "Failed to load");
    }
  }, []);

  useEffect(() => {
    load();
    const t = setInterval(load, 15000);
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

  return (
    <div className="space-y-5 pb-24">
      <header>
        <p className="text-[10px] font-semibold uppercase tracking-widest text-cyan-400/90">Phase 3</p>
        <h1 className="page-title text-2xl font-semibold text-white">Live Strategy Lab</h1>
        <p className="mt-1 text-sm text-zinc-400">
          Forward-tested strategies on genuine incoming data policies — simulated paper execution only.
        </p>
      </header>

      {err && <p className="rounded-lg border border-red-500/40 bg-red-950/30 px-3 py-2 text-sm text-red-200">{err}</p>}

      <section
        className={`rounded-xl border p-4 ${feedOk ? "border-emerald-500/30 bg-emerald-950/20" : "border-amber-500/40 bg-amber-950/20"}`}
      >
        <div className="flex flex-wrap items-center justify-between gap-2">
          <div>
            <p className="text-xs font-medium uppercase tracking-wide text-zinc-400">Feed</p>
            <p className="text-lg font-semibold text-white">
              {feed?.connection_status ?? "—"}
              <span className="ml-2 text-sm font-normal text-zinc-400">
                {feed?.latency_mode === "realtime" ? "Live" : (feed?.latency_mode ?? "—")}
              </span>
            </p>
            <p className="text-xs text-zinc-500">
              Provider {feed?.provider ?? "—"}
              {feed?.last_heartbeat_at ? ` · heartbeat ${new Date(feed.last_heartbeat_at).toLocaleTimeString()}` : ""}
            </p>
          </div>
          <Button variant="secondary" disabled={busy} onClick={tick}>
            Process tick
          </Button>
        </div>
        {!feedOk && (
          <p className="mt-2 text-xs text-amber-200/90">
            Strategies pause when the feed is disconnected, stale, or mislabeled. This is intentional.
          </p>
        )}
      </section>

      <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
        <Stat label="Active strategies" value={String(data?.active_strategy_count ?? 0)} />
        <Stat label="Paper equity" value={data ? `$${data.aggregate_equity.toLocaleString()}` : "—"} />
        <Stat label="Net P&amp;L" value={data ? `$${data.aggregate_net_pnl.toFixed(2)}` : "—"} />
        <Stat label="Market" value="MNQ · MES · MGC" />
      </div>

      <section className="space-y-3">
        <h2 className="text-sm font-semibold text-zinc-200">Forward test runs</h2>
        {!data?.runs?.length && (
          <p className="text-sm text-zinc-500">No runs yet. Start from Strategies with experimental or validated promotion.</p>
        )}
        {data?.runs?.map((r) => (
          <Link
            key={r.id}
            href={`/live-lab/${r.id}`}
            className="block rounded-xl border border-zinc-800 bg-zinc-900/60 p-4 active:bg-zinc-800"
          >
            <div className="flex items-start justify-between gap-2">
              <div>
                <p className="font-medium text-white">{r.strategy_name}</p>
                <p className="text-xs text-zinc-500">
                  {r.symbol} {r.timeframe} · {r.research_state.replaceAll("_", " ")}
                  {r.experimental ? " · experimental" : ""}
                </p>
              </div>
              <p className={`text-sm font-semibold ${r.net_pnl >= 0 ? "text-emerald-400" : "text-red-400"}`}>
                ${r.net_pnl.toFixed(2)}
              </p>
            </div>
            <p className="mt-2 text-xs text-zinc-500">
              {r.trade_count} trades · DD ${r.max_drawdown.toFixed(0)}
              {r.last_data_exchange_ts ? ` · data ${new Date(r.last_data_exchange_ts).toLocaleString()}` : ""}
            </p>
          </Link>
        ))}
      </section>

      <p className="text-[11px] text-zinc-600">{data?.disclaimer}</p>
    </div>
  );
}

function Stat({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-lg border border-zinc-800 bg-zinc-950/50 px-3 py-2">
      <p className="text-[10px] uppercase tracking-wide text-zinc-500">{label}</p>
      <p className="text-base font-semibold text-zinc-100">{value}</p>
    </div>
  );
}