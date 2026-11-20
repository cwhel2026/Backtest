"use client";

import { useParams } from "next/navigation";
import { useEffect, useRef, useState } from "react";
import {
  CandlestickSeries,
  createChart,
  LineSeries,
  type IChartApi,
  type UTCTimestamp,
} from "lightweight-charts";
import { Card } from "@/components/ui/Card";
import { Skeleton } from "@/components/ui/Skeleton";
import { apiFetch } from "@/lib/api";
import { latencyLabel } from "@/lib/navigation";

type Setup = {
  id: string;
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

type Bar = { ts: string; open: number; high: number; low: number; close: number };
type Overlay = { type: string; price?: number; ts?: string; label?: string };

export default function ScannerSetupDetailPage() {
  const { setupId } = useParams<{ setupId: string }>();
  const [setup, setSetup] = useState<Setup | null>(null);
  const [bars, setBars] = useState<Bar[]>([]);
  const [overlays, setOverlays] = useState<Overlay[]>([]);
  const [error, setError] = useState<string | null>(null);
  const chartRef = useRef<HTMLDivElement>(null);
  const chartApi = useRef<IChartApi | null>(null);

  useEffect(() => {
    if (!setupId) return;
    apiFetch<{ setup: Setup; bars: Bar[]; overlays: Overlay[] }>(`/api/v1/scanner/setups/${setupId}/chart-context`)
      .then((ctx) => {
        setSetup(ctx.setup);
        setBars(ctx.bars ?? []);
        setOverlays(ctx.overlays ?? []);
      })
      .catch((e) => setError(String(e)));
  }, [setupId]);

  useEffect(() => {
    if (!chartRef.current || !bars.length || !setup) return;
    chartApi.current?.remove();
    const chart = createChart(chartRef.current, {
      layout: { background: { color: "#0c0c0e" }, textColor: "#a1a1aa" },
      grid: { vertLines: { color: "#27272a" }, horzLines: { color: "#27272a" } },
      width: chartRef.current.clientWidth,
      height: 360,
    });
    chartApi.current = chart;
    const series = chart.addSeries(CandlestickSeries, {
      upColor: "#22c55e",
      downColor: "#ef4444",
      borderVisible: false,
      wickUpColor: "#22c55e",
      wickDownColor: "#ef4444",
    });
    series.setData(
      bars.map((b) => ({
        time: (Date.parse(b.ts) / 1000) as UTCTimestamp,
        open: b.open,
        high: b.high,
        low: b.low,
        close: b.close,
      })),
    );
    const addHline = (price: number | null, color: string) => {
      if (price == null) return;
      const line = chart.addSeries(LineSeries, { color, lineWidth: 1, lineStyle: 2 });
      const t0 = (Date.parse(bars[0].ts) / 1000) as UTCTimestamp;
      const t1 = (Date.parse(bars[bars.length - 1].ts) / 1000) as UTCTimestamp;
      line.setData([
        { time: t0, value: price },
        { time: t1, value: price },
      ]);
    };
    addHline(setup.entry_price, "#38bdf8");
    addHline(setup.stop_price, "#f87171");
    addHline(setup.target_price, "#4ade80");
    chart.timeScale().fitContent();
    const onResize = () => {
      if (chartRef.current) chart.applyOptions({ width: chartRef.current.clientWidth });
    };
    window.addEventListener("resize", onResize);
    return () => {
      window.removeEventListener("resize", onResize);
      chart.remove();
    };
  }, [bars, setup]);

  if (error) {
    return <Card className="text-sm text-red-200">{error}</Card>;
  }

  if (!setup) {
    return <Skeleton className="h-40" />;
  }

  return (
    <div className="space-y-4 pb-10">
      <header>
        <h1 className="page-title">
          {setup.strategy_name} · {setup.symbol}
        </h1>
        <p className="page-sub">
          {setup.status.replaceAll("_", " ")} · {latencyLabel(setup.feed_latency_mode)} · {setup.direction}
        </p>
      </header>

      <Card className="panel space-y-2 text-sm text-zinc-300">
        <p>{setup.explanation ?? "No narrative stored for this setup."}</p>
        <p className="text-xs text-zinc-500">
          Signal bar: {new Date(setup.market_ts).toLocaleString()} · R:R {setup.risk_reward ?? "—"}
        </p>
        {overlays.length ? (
          <ul className="text-xs text-zinc-500">
            {overlays.map((o, i) => (
              <li key={i}>
                {o.label ?? o.type}
                {o.price != null ? ` @ ${o.price}` : ""}
              </li>
            ))}
          </ul>
        ) : null}
      </Card>

      <Card className="panel overflow-hidden p-2">
        <div ref={chartRef} className="w-full" />
        {bars.length === 0 ? <p className="p-4 text-sm text-zinc-500">No OHLC candles in store for chart.</p> : null}
      </Card>
    </div>
  );
}