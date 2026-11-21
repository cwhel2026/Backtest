"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { Card } from "@/components/ui/Card";
import { EmptyState } from "@/components/ui/EmptyState";
import { apiFetch } from "@/lib/api";
import { latencyLabel } from "@/lib/navigation";

type Setup = {
  id: string;
  setup_id: string;
  symbol: string;
  strategy_name: string;
  direction: string;
  entry_price: number | null;
  stop_price: number | null;
  target_price: number | null;
  risk_reward: number | null;
  status: string;
  market_ts: string;
  explanation: string | null;
  feed_latency_mode: string | null;
  diagnostics: Record<string, unknown>;
};

type Platform = {
  market_data: {
    latency_mode: string;
    connection_status: string;
    provider: string | null;
    platform_active: boolean;
  };
  cme_session?: { headline: string; market_open_now: boolean; session_day: boolean };
  workers: { worker_name: string; stale: boolean; last_success_at: string | null; detail?: Record<string, unknown> }[];
};

export default function MarketScannerPage() {
  const [setups, setSetups] = useState<Setup[]>([]);
  const [platform, setPlatform] = useState<Platform | null>(null);
  const [loading, setLoading] = useState(true);
  const [symbol, setSymbol] = useState<string | "">("");

  useEffect(() => {
    const q = symbol ? `?symbol=${symbol}&limit=100` : "?limit=100";
    Promise.all([
      apiFetch<{ items: Setup[] }>(`/api/v1/scanner/setups${q}`),
      apiFetch<Platform>("/api/v1/platform/status"),
    ])
      .then(([s, p]) => {
        setSetups(s.items);
        setPlatform(p);
      })
      .catch(() => {})
      .finally(() => setLoading(false));
  }, [symbol]);

  const latency = latencyLabel(platform?.market_data?.latency_mode);

  return (
    <div className="space-y-6 pb-8">
      <header>
        <h1 className="page-title">Market Scanner</h1>
        <p className="page-sub">
          Incremental strategy detections on MNQ, MES, and MGC — includes rejected diagnostics when engines decline a
          candidate. Data class: <strong className="font-medium text-zinc-300">{latency}</strong>.
        </p>
      </header>

      <Card className="panel flex flex-wrap items-center gap-3 text-sm text-zinc-400">
        <span>
          Feed: <span className="text-zinc-200">{platform?.market_data.connection_status ?? "—"}</span>
        </span>
        <span>Provider {platform?.market_data.provider ?? "—"}</span>
        <span>
          CME:{" "}
          <span className="text-zinc-200">{platform?.cme_session?.headline ?? "—"}</span>
        </span>
        <span>
          Workers:{" "}
          {platform?.workers?.map((w) => `${w.worker_name}${w.stale ? " (stale)" : ""}`).join(" · ") || "No beats yet"}
        </span>
        <div className="ml-auto flex gap-2">
          {["", "MNQ", "MES", "MGC"].map((sym) => (
            <button
              key={sym || "all"}
              type="button"
              onClick={() => setSymbol(sym)}
              className={`rounded px-2 py-1 text-xs ${symbol === sym ? "bg-[var(--accent)]/20 text-zinc-100" : "text-zinc-500"}`}
            >
              {sym || "All"}
            </button>
          ))}
        </div>
      </Card>

      {loading ? (
        <p className="text-sm text-zinc-500">Loading setups…</p>
      ) : setups.length === 0 ? (
        <EmptyState
          title="No setups in database"
          description="Start replay ingestion and wait for closed 5m bars. Scanner rows are written when Berg TNB, Liquidity Sweep, or Anchor BOS engines emit orders on a bar close."
          actionHref="/settings"
          actionLabel="Settings & data"
        />
      ) : (
        <div className="data-table-wrap">
          <table>
            <thead className="border-b border-[var(--border)] text-xs uppercase text-zinc-500">
              <tr>
                <th className="px-3 py-2 text-left">Strategy</th>
                <th className="px-3 py-2 text-left">Symbol</th>
                <th className="px-3 py-2">Dir</th>
                <th className="px-3 py-2 text-right">Entry</th>
                <th className="px-3 py-2 text-right">Stop</th>
                <th className="px-3 py-2 text-right">Target</th>
                <th className="px-3 py-2 text-right">R:R</th>
                <th className="px-3 py-2">Status</th>
              </tr>
            </thead>
            <tbody>
              {setups.map((s) => (
                <tr key={s.id} className="border-b border-[var(--border)]/60 hover:bg-white/5">
                  <td className="px-3 py-2">
                    <Link href={`/scanner/${s.id}`} className="text-[var(--accent)]">
                      {s.strategy_name}
                    </Link>
                  </td>
                  <td className="px-3 py-2 text-zinc-300">{s.symbol}</td>
                  <td className="px-3 py-2 text-center text-zinc-400">{s.direction}</td>
                  <td className="px-3 py-2 text-right tabular-nums">{s.entry_price ?? "—"}</td>
                  <td className="px-3 py-2 text-right tabular-nums">{s.stop_price ?? "—"}</td>
                  <td className="px-3 py-2 text-right tabular-nums">{s.target_price ?? "—"}</td>
                  <td className="px-3 py-2 text-right tabular-nums">{s.risk_reward ?? "—"}</td>
                  <td className="px-3 py-2 text-xs text-zinc-400">{s.status.replaceAll("_", " ")}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}