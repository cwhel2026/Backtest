"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { Card } from "@/components/ui/Card";
import { EmptyState } from "@/components/ui/EmptyState";
import { PnlText } from "@/components/ui/PnlText";
import { apiFetch } from "@/lib/api";
import { latencyLabel, SCAN_SYMBOLS } from "@/lib/navigation";

type MarketRow = {
  symbol: string;
  lastCandle: string | null;
  runs: { strategy_name: string; state: string; net_pnl: number; trade_count: number }[];
};

export default function MarketScannerPage() {
  const [rows, setRows] = useState<MarketRow[]>([]);
  const [feed, setFeed] = useState<{ latency_mode: string; connection_status: string; provider: string | null } | null>(
    null,
  );
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    async function load() {
      const dash = await apiFetch<{
        feed: { latency_mode: string; connection_status: string; provider: string | null };
        runs: { symbol: string; strategy_name: string; research_state: string; net_pnl: number; trade_count: number }[];
      }>("/api/v1/live-lab/dashboard");

      setFeed(dash.feed);
      const out: MarketRow[] = [];
      for (const sym of SCAN_SYMBOLS) {
        let lastCandle: string | null = null;
        try {
          const candles = await apiFetch<{ bars: { ts: string }[] }>(
            `/api/v1/live-lab/candles?symbol=${sym}&timeframe=5m&limit=1`,
          );
          lastCandle = candles.bars?.[0]?.ts ?? null;
        } catch {
          lastCandle = null;
        }
        const runs = dash.runs
          .filter((r) => r.symbol === sym)
          .map((r) => ({
            strategy_name: r.strategy_name,
            state: r.research_state,
            net_pnl: r.net_pnl,
            trade_count: r.trade_count,
          }));
        out.push({ symbol: sym, lastCandle, runs });
      }
      setRows(out);
      setLoading(false);
    }
    load().catch(() => setLoading(false));
  }, []);

  const latency = latencyLabel(feed?.latency_mode);

  return (
    <div className="space-y-6 pb-8">
      <header>
        <h1 className="page-title">Market Scanner</h1>
        <p className="page-sub">
          Micro futures status, last stored candle, and paper-run activity. Prices are{" "}
          <strong className="font-medium text-zinc-300">{latency}</strong> — not implied live fills.
        </p>
      </header>

      <Card className="panel text-sm text-zinc-400">
        Feed: <span className="text-zinc-200">{feed?.connection_status ?? "—"}</span> · Provider{" "}
        {feed?.provider ?? "—"}
      </Card>

      {loading ? (
        <p className="text-sm text-zinc-500">Loading markets…</p>
      ) : (
        <ul className="space-y-4">
          {rows.map((row) => (
            <li key={row.symbol}>
              <Card className="panel space-y-3">
                <div className="flex flex-wrap items-baseline justify-between gap-2">
                  <h2 className="text-lg font-semibold text-zinc-50">{row.symbol}</h2>
                  <span className="text-xs text-zinc-500">
                    Last 5m close: {row.lastCandle ? new Date(row.lastCandle).toLocaleString() : "No candles in store"}
                  </span>
                </div>
                {row.runs.length === 0 ? (
                  <p className="text-sm text-zinc-500">No paper runs monitoring {row.symbol}.</p>
                ) : (
                  <div className="data-table-wrap">
                    <table>
                      <thead className="border-b border-[var(--border)] text-xs uppercase text-zinc-500">
                        <tr>
                          <th className="px-3 py-2">Strategy</th>
                          <th className="px-3 py-2">Paper state</th>
                          <th className="px-3 py-2">Trades</th>
                          <th className="px-3 py-2 text-right">Sim. P&amp;L</th>
                        </tr>
                      </thead>
                      <tbody>
                        {row.runs.map((r, i) => (
                          <tr key={i} className="border-b border-[var(--border)]/60">
                            <td className="px-3 py-2 text-zinc-200">{r.strategy_name}</td>
                            <td className="px-3 py-2 text-zinc-400">{r.state.replaceAll("_", " ")}</td>
                            <td className="px-3 py-2 text-zinc-400">{r.trade_count}</td>
                            <td className="px-3 py-2 text-right">
                              <PnlText value={r.net_pnl} />
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                )}
                <Link href="/paper-trading" className="text-sm text-[var(--accent)]">
                  Manage paper runs →
                </Link>
              </Card>
            </li>
          ))}
        </ul>
      )}

      {!loading && rows.every((r) => !r.lastCandle && !r.runs.length) ? (
        <EmptyState
          title="Scanner needs data"
          description="Ingest historical or replay market events so candles exist for MNQ, MES, and MGC. Then start a paper run from Strategy Lab."
          actionHref="/settings"
          actionLabel="Settings & data"
        />
      ) : null}
    </div>
  );
}