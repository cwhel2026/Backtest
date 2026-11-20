"use client";

import Link from "next/link";
import { useEffect, useMemo, useState } from "react";
import { Card } from "@/components/ui/Card";
import { PnlText } from "@/components/ui/PnlText";
import { apiFetch } from "@/lib/api";

type LeaderRow = {
  run_id: string;
  strategy_name: string;
  symbol: string;
  grade: string;
  passes_prop_screen: boolean;
  gate_miss: string | null;
  metrics: Record<string, string | number>;
  tests: Record<string, unknown>;
  rank_score: number;
  completed_at: string | null;
};

type Centre = {
  disclaimer: string;
  summary: { tests_completed: number; validated_count: number; rejected_count: number; active_experiments: number };
  active_jobs: { id: string; title: string; status: string; message: string; progress_pct: number }[];
  leaderboard: LeaderRow[];
  validated_candidates: LeaderRow[];
  rejected_candidates: LeaderRow[];
};

export default function ResearchPage() {
  const [data, setData] = useState<Centre | null>(null);
  const [q, setQ] = useState("");
  const [sort, setSort] = useState<"rank" | "name">("rank");
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    apiFetch<Centre>("/api/v1/research/centre")
      .then(setData)
      .finally(() => setLoading(false));
    const t = setInterval(() => {
      apiFetch<Centre>("/api/v1/research/centre").then(setData).catch(() => {});
    }, 15000);
    return () => clearInterval(t);
  }, []);

  const rows = useMemo(() => {
    let list = data?.leaderboard ?? [];
    if (q.trim()) {
      const needle = q.toLowerCase();
      list = list.filter(
        (r) =>
          r.strategy_name.toLowerCase().includes(needle) ||
          r.symbol.toLowerCase().includes(needle) ||
          r.grade.toLowerCase().includes(needle),
      );
    }
    if (sort === "rank") {
      return [...list].sort((a, b) => b.rank_score - a.rank_score);
    }
    return [...list].sort((a, b) => a.strategy_name.localeCompare(b.strategy_name));
  }, [data, q, sort]);

  return (
    <div className="space-y-6 pb-10">
      <header>
        <h1 className="page-title">AI Research Centre</h1>
        <p className="page-sub">Ranked historical evidence — walk-forward and out-of-sample fields when present. Not live profit.</p>
      </header>

      {loading ? <p className="text-sm text-zinc-500">Loading research…</p> : null}

      {data ? (
        <>
          <div className="grid gap-3 sm:grid-cols-4">
            <Stat label="Tests completed" value={data.summary.tests_completed} />
            <Stat label="Validated" value={data.summary.validated_count} />
            <Stat label="Rejected" value={data.summary.rejected_count} />
            <Stat label="Running now" value={data.summary.active_experiments} />
          </div>

          {data.active_jobs.length > 0 ? (
            <Card className="panel space-y-2">
              <h2 className="text-sm font-semibold text-zinc-200">In progress</h2>
              <ul className="space-y-2 text-sm">
                {data.active_jobs.map((j) => (
                  <li key={j.id} className="text-zinc-400">
                    {j.title} · {j.status} · {j.progress_pct}%
                    <span className="block text-xs text-zinc-600">{j.message}</span>
                  </li>
                ))}
              </ul>
            </Card>
          ) : null}

          <Card className="panel space-y-3">
            <div className="flex flex-wrap gap-2">
              <input
                className="min-h-[40px] flex-1 rounded-lg border border-[var(--border)] bg-[var(--card-elevated)] px-3 text-sm"
                placeholder="Search strategy or symbol…"
                value={q}
                onChange={(e) => setQ(e.target.value)}
              />
              <select
                className="rounded-lg border border-[var(--border)] bg-[var(--card-elevated)] px-3 text-sm"
                value={sort}
                onChange={(e) => setSort(e.target.value as "rank" | "name")}
              >
                <option value="rank">Sort: risk-adjusted rank</option>
                <option value="name">Sort: name</option>
              </select>
            </div>
            <p className="text-xs text-zinc-600">{data.disclaimer}</p>
            <div className="data-table-wrap">
              <table>
                <thead className="border-b border-[var(--border)] text-xs uppercase text-zinc-500">
                  <tr>
                    <th className="px-2 py-2 text-left">Strategy</th>
                    <th className="px-2 py-2">Symbol</th>
                    <th className="px-2 py-2">Grade</th>
                    <th className="px-2 py-2 text-right">Net P&amp;L</th>
                    <th className="px-2 py-2 text-right">Win %</th>
                    <th className="px-2 py-2 text-right">PF</th>
                    <th className="px-2 py-2 text-right">Trades</th>
                  </tr>
                </thead>
                <tbody>
                  {rows.map((r) => (
                    <tr key={r.run_id} className="border-b border-[var(--border)]/50">
                      <td className="px-2 py-2">
                        <Link href={`/backtests/${r.run_id}`} className="text-[var(--accent)]">
                          {r.strategy_name}
                        </Link>
                        {!r.passes_prop_screen && r.gate_miss ? (
                          <span className="block text-xs text-amber-200/80">{r.gate_miss}</span>
                        ) : null}
                      </td>
                      <td className="px-2 py-2 text-center text-zinc-400">{r.symbol}</td>
                      <td className="px-2 py-2 text-center text-xs">{r.grade}</td>
                      <td className="px-2 py-2 text-right">
                        {typeof r.metrics.net_profit_usd === "number" ? (
                          <PnlText value={Number(r.metrics.net_profit_usd)} />
                        ) : (
                          <span className="text-zinc-500">—</span>
                        )}
                      </td>
                      <td className="px-2 py-2 text-right text-zinc-400">{r.metrics.win_rate ?? "—"}</td>
                      <td className="px-2 py-2 text-right text-zinc-400">{r.metrics.profit_factor ?? "—"}</td>
                      <td className="px-2 py-2 text-right text-zinc-400">{r.metrics.trade_count ?? "—"}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </Card>
        </>
      ) : null}
    </div>
  );
}

function Stat({ label, value }: { label: string; value: number }) {
  return (
    <Card className="panel">
      <p className="metric-label">{label}</p>
      <p className="metric-value">{value}</p>
    </Card>
  );
}