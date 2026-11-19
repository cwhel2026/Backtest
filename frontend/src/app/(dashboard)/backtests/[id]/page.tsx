"use client";

import { useParams } from "next/navigation";
import { useEffect, useRef, useState } from "react";
import {
  CandlestickSeries,
  LineSeries,
  createChart,
  createSeriesMarkers,
  type IChartApi,
  type UTCTimestamp,
} from "lightweight-charts";
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
  entry_price: number;
  exit_price: number;
  stop_price?: number | null;
  target_price?: number | null;
  net_pnl: number;
  exit_reason: string;
  meta?: {
    signal_reason?: string;
    entry_mode?: string;
    order_events?: { event: string; detail: string; ts: string }[];
    setup?: Record<string, unknown>;
  };
};

type OhlcvBar = { ts: string; open: number; high: number; low: number; close: number; volume: number };

export default function BacktestDetailPage() {
  const { id } = useParams<{ id: string }>();
  const [run, setRun] = useState<Backtest | null>(null);
  const [trades, setTrades] = useState<Trade[]>([]);
  const [selectedTrade, setSelectedTrade] = useState<number | null>(null);
  const chartRef = useRef<HTMLDivElement>(null);
  const tradeChartRef = useRef<HTMLDivElement>(null);
  const chartApi = useRef<IChartApi | null>(null);
  const tradeChartApi = useRef<IChartApi | null>(null);

  useEffect(() => {
    if (!id) return;
    Promise.all([
      apiFetch<Backtest>(`/api/v1/backtests/${id}`),
      apiFetch<Trade[]>(`/api/v1/backtests/${id}/trades`),
    ]).then(([r, t]) => {
      setRun(r);
      setTrades(t);
      if (t.length) setSelectedTrade(t[0].trade_number);
    });
  }, [id]);

  useEffect(() => {
    const host = chartRef.current;
    if (!host || trades.length === 0) return;

    const chart = createChart(host, {
      layout: { background: { color: "#181b22" }, textColor: "#a1a1aa" },
      grid: { vertLines: { color: "#27272a" }, horzLines: { color: "#27272a" } },
      width: host.clientWidth,
      height: 220,
    });
    chartApi.current = chart;

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

    const onResize = () => {
      const active = chartApi.current;
      const el = chartRef.current;
      if (!active || !el) return;
      try {
        active.applyOptions({ width: el.clientWidth });
      } catch {
        /* chart teardown can race the resize handler */
      }
    };
    window.addEventListener("resize", onResize);

    return () => {
      window.removeEventListener("resize", onResize);
      chartApi.current = null;
      chart.remove();
    };
  }, [trades]);

  useEffect(() => {
    const host = tradeChartRef.current;
    if (!host || !id || selectedTrade == null) return;

    const chart = createChart(host, {
      layout: { background: { color: "#181b22" }, textColor: "#a1a1aa" },
      grid: { vertLines: { color: "#27272a" }, horzLines: { color: "#27272a" } },
      width: host.clientWidth,
      height: 360,
      timeScale: { timeVisible: true, secondsVisible: false },
    });
    tradeChartApi.current = chart;
    const candles = chart.addSeries(CandlestickSeries, {
      upColor: "#34d399",
      downColor: "#f87171",
      borderVisible: false,
      wickUpColor: "#34d399",
      wickDownColor: "#f87171",
    });
    const markers = createSeriesMarkers(candles);

    let cancelled = false;
    (async () => {
      const bars = await apiFetch<OhlcvBar[]>(
        `/api/v1/backtests/${id}/chart-bars?trade_number=${selectedTrade}&padding=60`
      );
      if (cancelled) return;
      const trade = trades.find((t) => t.trade_number === selectedTrade);
      candles.setData(
        bars.map((b) => ({
          time: Math.floor(new Date(b.ts).getTime() / 1000) as UTCTimestamp,
          open: b.open,
          high: b.high,
          low: b.low,
          close: b.close,
        }))
      );
      if (trade) {
        markers.setMarkers([
          {
            time: Math.floor(new Date(trade.entry_ts).getTime() / 1000) as UTCTimestamp,
            position: trade.direction === "long" ? "belowBar" : "aboveBar",
            color: "#60a5fa",
            shape: trade.direction === "long" ? "arrowUp" : "arrowDown",
            text: "Entry",
          },
          {
            time: Math.floor(new Date(trade.exit_ts).getTime() / 1000) as UTCTimestamp,
            position: "inBar",
            color: "#fbbf24",
            shape: "circle",
            text: trade.exit_reason,
          },
        ]);
        if (trade.stop_price != null) {
          candles.createPriceLine({
            price: trade.stop_price,
            color: "#f87171",
            lineWidth: 1,
            lineStyle: 2,
            title: "Stop",
          });
        }
        if (trade.target_price != null) {
          candles.createPriceLine({
            price: trade.target_price,
            color: "#34d399",
            lineWidth: 1,
            lineStyle: 2,
            title: "Target",
          });
        }
      }
      chart.timeScale().fitContent();
    })();

    const onResize = () => {
      const active = tradeChartApi.current;
      const el = tradeChartRef.current;
      if (!active || !el) return;
      try {
        active.applyOptions({ width: el.clientWidth });
      } catch {
        /* noop */
      }
    };
    window.addEventListener("resize", onResize);

    return () => {
      cancelled = true;
      window.removeEventListener("resize", onResize);
      tradeChartApi.current = null;
      chart.remove();
    };
  }, [id, selectedTrade, trades]);

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

      {trades.length > 0 ? (
        <section className="space-y-2">
          <div className="flex flex-col gap-2 md:flex-row md:items-center md:justify-between">
            <h3 className="text-sm font-medium text-zinc-300">Trade chart (OHLCV window)</h3>
            <label className="flex items-center gap-2 text-sm text-zinc-400">
              Trade #
              <select
                className="rounded-md border border-zinc-700 bg-zinc-900 px-2 py-1"
                value={selectedTrade ?? ""}
                onChange={(e) => setSelectedTrade(Number(e.target.value))}
              >
                {trades.map((t) => (
                  <option key={t.trade_number} value={t.trade_number}>
                    {t.trade_number} · {t.direction} · {t.net_pnl.toFixed(2)}
                  </option>
                ))}
              </select>
            </label>
          </div>
          <div ref={tradeChartRef} className="w-full rounded-lg border border-zinc-800" />
        </section>
      ) : null}

      {run.metrics ? (
        <MetricsGrid metrics={run.metrics} />
      ) : (
        <p className="text-sm text-zinc-500">Status: {run.status}</p>
      )}

      <section>
        <h3 className="text-sm font-medium text-zinc-300">Trade ledger</h3>
        <TradesTable trades={trades} onSelect={setSelectedTrade} selected={selectedTrade} />
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
            {metrics[k] == null
              ? "—"
              : k === "win_rate" && typeof metrics[k] === "number"
                ? `${((metrics[k] as number) * 100).toFixed(1)}%`
                : typeof metrics[k] === "number"
                  ? (metrics[k] as number).toFixed(4)
                  : metrics[k]}
          </p>
        </div>
      ))}
    </div>
  );
}

function TradesTable({
  trades,
  onSelect,
  selected,
}: {
  trades: Trade[];
  onSelect: (n: number) => void;
  selected: number | null;
}) {
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
              <th className="px-3 py-2">Exit</th>
              <th className="px-3 py-2">Replay</th>
            </tr>
          </thead>
          <tbody>
            {trades.map((t) => (
              <tr
                key={t.trade_number}
                className={`cursor-pointer border-t border-zinc-800/80 hover:bg-zinc-900/40 ${
                  selected === t.trade_number ? "bg-zinc-900/60" : ""
                }`}
                onClick={() => onSelect(t.trade_number)}
              >
                <td className="px-3 py-2">{t.trade_number}</td>
                <td className="px-3 py-2">{t.direction}</td>
                <td className="px-3 py-2 text-xs">{t.entry_ts}</td>
                <td className="px-3 py-2 text-xs">{t.exit_ts}</td>
                <td className="px-3 py-2">{t.net_pnl.toFixed(2)}</td>
                <td className="px-3 py-2 text-xs">{t.exit_reason}</td>
                <td className="px-3 py-2 text-xs text-zinc-400">
                  {t.meta?.signal_reason ?? "—"}
                  {t.meta?.entry_mode === "limit" ? " · limit" : ""}
                  {t.meta?.order_events?.length
                    ? ` · ${t.meta.order_events.map((e) => e.event).join(" → ")}`
                    : ""}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </ScrollTable>
  );
}