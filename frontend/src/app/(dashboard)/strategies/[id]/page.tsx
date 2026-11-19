"use client";

import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import { FormEvent, useEffect, useState } from "react";
import { apiFetch } from "@/lib/api";

type Dataset = { id: string; instrument_id: string; timeframe: string; row_count: number };

type StrategyDetail = {
  id: string;
  name: string;
  symbol: string;
  category: string;
  timeframe: string;
  lifecycle: string;
  current_version: { id: string; specification: Record<string, unknown>; version_number: number } | null;
  latest_backtest: { id: string; reproducibility_id: string; metrics: Record<string, number | null> } | null;
};

export default function StrategyDetailPage() {
  const { id } = useParams<{ id: string }>();
  const router = useRouter();
  const [detail, setDetail] = useState<StrategyDetail | null>(null);
  const [cloning, setCloning] = useState(false);
  const [datasets, setDatasets] = useState<Dataset[]>([]);
  const [datasetId, setDatasetId] = useState("");
  const [backtestStatus, setBacktestStatus] = useState<string | null>(null);
  const [running, setRunning] = useState(false);

  async function cloneStrategy() {
    if (!id) return;
    setCloning(true);
    try {
      const copy = await apiFetch<StrategyDetail>(`/api/v1/strategies/${id}/clone`, {
        method: "POST",
        body: JSON.stringify({}),
      });
      router.push(`/strategies/${copy.id}`);
    } finally {
      setCloning(false);
    }
  }

  useEffect(() => {
    if (!id) return;
    apiFetch<StrategyDetail>(`/api/v1/strategies/${id}`).then(setDetail);
    apiFetch<Dataset[]>("/api/v1/market-data/datasets").then(setDatasets);
  }, [id]);

  useEffect(() => {
    if (!detail || datasets.length === 0) return;
    const match = datasets.filter(
      (d) => d.timeframe === detail.timeframe && d.row_count > 0
    );
    if (match.length && !datasetId) setDatasetId(match[0].id);
  }, [detail, datasets, datasetId]);

  async function runBacktest(e: FormEvent) {
    e.preventDefault();
    if (!id || !detail?.current_version || !datasetId) return;
    setRunning(true);
    setBacktestStatus(null);
    try {
      const run = await apiFetch<{ id: string; status: string }>("/api/v1/backtests", {
        method: "POST",
        body: JSON.stringify({
          strategy_id: id,
          strategy_version_id: detail.current_version.id,
          dataset_id: datasetId,
          assumptions: { slippage_ticks_per_side: 1 },
        }),
      });
      let status = run.status;
      for (let i = 0; i < 60 && status !== "completed" && status !== "failed"; i++) {
        await new Promise((r) => setTimeout(r, 1500));
        const polled = await apiFetch<{ status: string; error?: string }>(`/api/v1/backtests/${run.id}`);
        status = polled.status;
        if (status === "failed") {
          setBacktestStatus(polled.error || "Backtest failed");
          setRunning(false);
          return;
        }
      }
      if (status === "completed") {
        router.push(`/backtests/${run.id}`);
        return;
      }
      setBacktestStatus("Backtest still running — check Backtests list shortly.");
    } catch (err) {
      setBacktestStatus(String(err));
    } finally {
      setRunning(false);
    }
  }

  if (!detail) return <p className="text-zinc-500">Loading strategy…</p>;

  return (
    <div className="space-y-6 max-w-4xl">
      <header className="flex flex-col gap-3 md:flex-row md:items-start md:justify-between">
        <div>
          <h2 className="page-title">{detail.name}</h2>
          <p className="page-sub">
            {detail.symbol} · {detail.category} · {detail.timeframe} · {detail.lifecycle}
          </p>
        </div>
        <button
          type="button"
          disabled={cloning}
          onClick={cloneStrategy}
          className="rounded-md border border-zinc-700 px-3 py-2 text-sm text-zinc-200 hover:bg-zinc-900 disabled:opacity-50"
        >
          {cloning ? "Cloning…" : "Clone"}
        </button>
      </header>

      {detail.latest_backtest ? (
        <section className="rounded-lg border border-zinc-800 bg-[#181b22] p-4 text-sm">
          <p className="font-medium text-zinc-200">Latest backtest (historical simulation only)</p>
          <p className="mt-2 text-zinc-400">
            Repro ID: <span className="font-mono text-xs">{detail.latest_backtest.reproducibility_id}</span>
          </p>
          <Link href={`/backtests/${detail.latest_backtest.id}`} className="mt-2 inline-block text-emerald-400">
            View run →
          </Link>
        </section>
      ) : (
        <p className="text-sm text-zinc-500">No completed backtests yet.</p>
      )}

      {detail.current_version ? (
        <section className="rounded-lg border border-zinc-800 bg-[#181b22] p-4">
          <h3 className="text-sm font-medium text-zinc-200">Run historical backtest</h3>
          <p className="mt-1 text-xs text-zinc-500">
            Simulation only — uses imported OHLCV for {detail.symbol} · {detail.timeframe}.
          </p>
          <form onSubmit={runBacktest} className="mt-3 flex flex-col gap-3 md:flex-row md:items-end">
            <label className="flex flex-1 flex-col gap-1 text-sm text-zinc-400">
              Dataset
              <select
                className="rounded-md border border-zinc-700 bg-zinc-900 px-3 py-2"
                value={datasetId}
                onChange={(e) => setDatasetId(e.target.value)}
              >
                <option value="">Select dataset…</option>
                {datasets
                  .filter((d) => d.timeframe === detail.timeframe)
                  .map((d) => (
                    <option key={d.id} value={d.id}>
                      {d.timeframe} · {d.row_count} bars · {d.id.slice(0, 8)}
                    </option>
                  ))}
              </select>
            </label>
            <button
              type="submit"
              disabled={running || !datasetId}
              className="rounded-md bg-emerald-700 px-4 py-2 text-sm text-white hover:bg-emerald-600 disabled:opacity-50"
            >
              {running ? "Running…" : "Run backtest"}
            </button>
          </form>
          {backtestStatus ? <p className="mt-2 text-sm text-zinc-400">{backtestStatus}</p> : null}
        </section>
      ) : null}

      {detail.current_version ? (
        <section>
          <h3 className="text-sm font-medium text-zinc-300">Executable specification v{detail.current_version.version_number}</h3>
          <pre className="mt-2 overflow-auto rounded-lg border border-zinc-800 bg-black/40 p-4 text-xs text-zinc-300">
            {JSON.stringify(detail.current_version.specification, null, 2)}
          </pre>
        </section>
      ) : null}
    </div>
  );
}