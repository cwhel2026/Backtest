"use client";

import Link from "next/link";
import { FormEvent, useEffect, useState } from "react";
import { apiFetch } from "@/lib/api";

type Dataset = { id: string; timeframe: string; row_count: number; meta?: { label?: string } };
type Strategy = { id: string; name: string; symbol: string | null };
type Backtest = {
  id: string;
  strategy_id: string;
  status: string;
  reproducibility_id: string;
  metrics: { total_net_profit?: number; trade_count?: number; profit_factor?: number } | null;
  performance_category: string;
};

export default function BacktestsPage() {
  const [datasets, setDatasets] = useState<Dataset[]>([]);
  const [strategies, setStrategies] = useState<Strategy[]>([]);
  const [runs, setRuns] = useState<Backtest[]>([]);
  const [strategyId, setStrategyId] = useState("");
  const [datasetId, setDatasetId] = useState("");
  const [message, setMessage] = useState<string | null>(null);

  useEffect(() => {
    Promise.all([
      apiFetch<Dataset[]>("/api/v1/market-data/datasets"),
      apiFetch<Strategy[]>("/api/v1/strategies"),
      apiFetch<Backtest[]>("/api/v1/backtests"),
    ]).then(([d, s, r]) => {
      setDatasets(d.filter((x) => x.row_count > 0));
      setStrategies(s);
      setRuns(r);
      if (s[0]) setStrategyId(s[0].id);
      if (d[0]) setDatasetId(d[0].id);
    });
  }, []);

  async function onSubmit(e: FormEvent) {
    e.preventDefault();
    setMessage(null);
    try {
      const res = await apiFetch<Backtest>("/api/v1/backtests", {
        method: "POST",
        body: JSON.stringify({
          strategy_id: strategyId,
          dataset_id: datasetId,
          assumptions: { slippage_ticks_per_side: 1 },
        }),
      });
      setMessage(`Queued backtest ${res.id} — refresh when worker completes.`);
      const list = await apiFetch<Backtest[]>("/api/v1/backtests");
      setRuns(list);
    } catch (err) {
      setMessage(String(err));
    }
  }

  return (
    <div className="space-y-8">
      <header>
        <h2 className="text-2xl font-semibold text-white">Backtest laboratory</h2>
        <p className="mt-1 text-sm text-zinc-500">
          Event-driven simulation with reproducibility ID. Results are{" "}
          <span className="text-zinc-300">{runs[0]?.performance_category || "backtest"}</span> only.
        </p>
      </header>

      <form onSubmit={onSubmit} className="rounded-lg border border-zinc-800 bg-[#181b22] p-6">
        <h3 className="text-sm font-medium text-zinc-200">Run backtest</h3>
        <div className="mt-4 flex flex-wrap gap-4">
          <label className="text-sm text-zinc-400">
            Strategy
            <select
              className="ml-2 rounded-md border border-zinc-700 bg-zinc-900 px-2 py-1"
              value={strategyId}
              onChange={(e) => setStrategyId(e.target.value)}
            >
              {strategies.map((s) => (
                <option key={s.id} value={s.id}>
                  {s.name}
                </option>
              ))}
            </select>
          </label>
          <label className="text-sm text-zinc-400">
            Dataset
            <select
              className="ml-2 rounded-md border border-zinc-700 bg-zinc-900 px-2 py-1"
              value={datasetId}
              onChange={(e) => setDatasetId(e.target.value)}
            >
              {datasets.length === 0 ? (
                <option value="">Import CSV on Market Data first</option>
              ) : (
                datasets.map((d) => (
                  <option key={d.id} value={d.id}>
                    {d.meta?.label || d.id.slice(0, 8)} · {d.row_count} bars
                  </option>
                ))
              )}
            </select>
          </label>
          <button
            type="submit"
            disabled={!datasetId || !strategyId}
            className="rounded-md bg-emerald-700 px-4 py-2 text-sm text-white hover:bg-emerald-600 disabled:opacity-40"
          >
            Queue backtest
          </button>
        </div>
        {message ? <p className="mt-3 text-sm text-zinc-400">{message}</p> : null}
      </form>

      <section className="overflow-hidden rounded-lg border border-zinc-800">
        <table className="w-full text-left text-sm">
          <thead className="bg-zinc-900/80 text-xs uppercase text-zinc-500">
            <tr>
              <th className="px-4 py-3">Run</th>
              <th className="px-4 py-3">Status</th>
              <th className="px-4 py-3">Trades</th>
              <th className="px-4 py-3">Net P&L</th>
              <th className="px-4 py-3">PF</th>
              <th className="px-4 py-3">Repro ID</th>
            </tr>
          </thead>
          <tbody>
            {runs.map((r) => (
              <tr key={r.id} className="border-t border-zinc-800/80">
                <td className="px-4 py-3">
                  <Link className="text-emerald-400 hover:underline" href={`/backtests/${r.id}`}>
                    {r.id.slice(0, 8)}
                  </Link>
                </td>
                <td className="px-4 py-3">{r.status}</td>
                <td className="px-4 py-3">{r.metrics?.trade_count ?? "—"}</td>
                <td className="px-4 py-3">
                  {r.metrics?.total_net_profit != null ? r.metrics.total_net_profit.toFixed(2) : "—"}
                </td>
                <td className="px-4 py-3">
                  {r.metrics?.profit_factor != null ? r.metrics.profit_factor.toFixed(2) : "—"}
                </td>
                <td className="px-4 py-3 font-mono text-xs text-zinc-500">{r.reproducibility_id}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </section>
    </div>
  );
}