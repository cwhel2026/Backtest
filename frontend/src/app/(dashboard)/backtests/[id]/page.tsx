"use client";

import { useParams } from "next/navigation";
import { useEffect, useRef, useState } from "react";
import { LineSeries, createChart, type IChartApi, type UTCTimestamp } from "lightweight-charts";
import { ScrollTable } from "@/components/ScrollTable";
import { apiFetch } from "@/lib/api";

type Backtest = {
  id: string;
  status: string;
  reproducibility_id: string;
  engine_version: string;
  metrics: Record<string, number | null> | null;
  performance_category: string;
};

type Trade = {
  trade_number: number;
  direction: string;
  entry_ts: string;
  exit_ts: string;
  net_pnl: number;
  exit_reason: string;
};

export default function BacktestDetailPage() {
  const { id } = useParams<{ id: string }>();
  const [run, setRun] = useState<Backtest | null>(null);
  const [trades, setTrades] = useState<Trade[]>([]);
  const chartRef = useRef<HTMLDivElement>(null);
  const chartApi = useRef<IChartApi | null>(null);

  useEffect(() => {
    if (!id) return;
    Promise.all([
      apiFetch<Backtest>(`/api/v1/backtests/${id}`),
      apiFetch<Trade[]>(`/api/v1/backtests/${id}/trades`),
    ]).then(([r, t]) => {
      setRun(r);
      setTrades(t);
    });
  }, [id]);

  useEffect(() => {
    if (!chartRef.current || trades.length === 0) return;
    if (chartApi.current) chartApi.current.remove();
    const chart = createChart(chartRef.current, {
      layout: { background: { color: "#181b22" }, textColor: "#a1a1aa" },
      grid: { vertLines: { color: "#27272a" }, horzLines: { color: "#27272a" } },
      width: chartRef.current.clientWidth,
      height: 240,
    });
    const series = chart.addSeries(LineSeries, { color: "#34d399" });
    let eq = 100000;
    const data = trades.map((t) => {
      eq += t.net_pnl;
      return {
        time: Math.floor(new Date(t.exit_ts).getTime() / 1000) as UTCTimestamp,
        value: eq,
      };
    });
    series.setData(data);
    chartApi.current = chart;
    const onResize = () => {
      if (chartRef.current) chart.applyOptions({ width: chartRef.current.clientWidth });
    };
    window.addEventListener("resize", onResize);
    return () => {
      window.removeEventListener("resize", onResize);
      chart.remove();
    };
  }, [trades]);

  if (!run) return <p className="text-zinc-500">Loading backtest…</p>;

  return (
    <div className="space-y-8">
      <header>
        <h2 className="page-title">Backtest {id?.slice(0, 8)}</h2>
        <p className="page-sub break-words">
          Category: <span className="text-zinc-300">{run.performance_category}</span> · Engine{" "}
          {run.engine_version}
        </p>
        <p className="mt-1 break-all font-mono text-[10px] text-zinc-500 md:text-xs">
          Repro {run.reproducibility_id}
        </p>
      </header>

      <div ref={chartRef} className="w-full rounded-lg border border-zinc-800" />

      {run.metrics ? (
        <MetricsGrid metrics={run.metrics} />
      ) : (
        <p className="text-sm text-zinc-500">Status: {run.status}</p>
      )}

      <section>
        <h3 className="text-sm font-medium text-zinc-300">Trade ledger</h3>
        <TradesTable trades={trades} />
      </section>
    </div>
  );
}

function MetricsGrid({ metrics }: { metrics: Record<string, number | null> }) {
  const keys = ["trade_count", "total_net_profit", "profit_factor", "win_rate", "max_drawdown", "expectancy_per_trade"];
  return (
    <div className="grid gap-3 sm:grid-cols-3">
      {keys.map((k) => (
        <div key={k} className="rounded-lg border border-zinc-800 bg-[#181b22] p-4">
          <p className="text-xs uppercase text-zinc-500">{k.replaceAll("_", " ")}</p>
          <p className="mt-1 text-xl text-white">
            {metrics[k] == null ? "—" : typeof metrics[k] === "number" ? (metrics[k] as number).toFixed(4) : metrics[k]}
          </p>
        </div>
      ))}
    </div>
  );
}

function TradesTable({ trades }: { trades: Trade[] }) {
  return (
    <ScrollTable className="mt-3">
    <div className="overflow-hidden rounded-lg border border-zinc-800">
      <table className="w-full text-left text-sm">
        <thead className="bg-zinc-900/80 text-xs uppercase text-zinc-500">
          <tr>
            <th className="px-3 py-2">#</th>
            <th className="px-3 py-2">Dir</th>
            <th className="px-3 py-2">Entry</th>
            <th className="px-3 py-2">Exit</th>
            <th className="px-3 py-2">Net</th>
            <th className="px-3 py-2">Reason</th>
          </tr>
        </thead>
        <tbody>
          {trades.map((t) => (
            <tr key={t.trade_number} className="border-t border-zinc-800/80">
              <td className="px-3 py-2">{t.trade_number}</td>
              <td className="px-3 py-2">{t.direction}</td>
              <td className="px-3 py-2 text-xs">{t.entry_ts}</td>
              <td className="px-3 py-2 text-xs">{t.exit_ts}</td>
              <td className="px-3 py-2">{t.net_pnl.toFixed(2)}</td>
              <td className="px-3 py-2">{t.exit_reason}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
    </ScrollTable>
  );
}