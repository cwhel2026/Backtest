"use client";

import { useParams } from "next/navigation";
import { useCallback, useEffect, useRef, useState } from "react";
import { CandlestickSeries, createChart, type IChartApi, type UTCTimestamp } from "lightweight-charts";

import { Button } from "@/components/ui/Button";
import { apiFetch } from "@/lib/api";

type RunDetail = {
  run: {
    id: string;
    strategy_name: string;
    symbol: string;
    timeframe: string;
    research_state: string;
    experimental: boolean;
    net_pnl: number;
    equity: number;
    trade_count: number;
    max_drawdown: number;
    last_data_exchange_ts: string | null;
    strategy_phase: string | null;
    runner_state_version: number | null;
  };
  validation: { passed: boolean; reasons: string[] };
  ledger: {
    event_type: string;
    payload: Record<string, unknown>;
    exchange_ts: string | null;
    decision_ts: string | null;
    sequence: number;
  }[];
};

type ChartPayload = {
  bars: { ts: string; open: number; high: number; low: number; close: number }[];
  markers: { ts: string | null; type: string }[];
  equity_curve: { ts: string | null; equity: number }[];
  open_position: Record<string, unknown> | null;
  pending_orders: unknown[];
  run: { net_pnl: number; equity: number; trade_count: number };
};

export default function LiveStrategyRunPage() {
  const { runId } = useParams<{ runId: string }>();
  const [detail, setDetail] = useState<RunDetail | null>(null);
  const [chart, setChart] = useState<ChartPayload | null>(null);
  const chartRef = useRef<HTMLDivElement>(null);
  const chartApi = useRef<IChartApi | null>(null);

  const load = useCallback(async () => {
    if (!runId) return;
    const [d, c] = await Promise.all([
      apiFetch<RunDetail>(`/api/v1/live-lab/forward-tests/${runId}`),
      apiFetch<ChartPayload>(`/api/v1/live-lab/forward-tests/${runId}/chart`),
    ]);
    setDetail(d);
    setChart(c);
  }, [runId]);

  useEffect(() => {
    load();
    const t = setInterval(load, 20000);
    return () => clearInterval(t);
  }, [load]);

  useEffect(() => {
    if (!chartRef.current || !chart?.bars?.length) return;
    if (chartApi.current) chartApi.current.remove();
    const c = createChart(chartRef.current, {
      layout: { background: { color: "#09090b" }, textColor: "#a1a1aa" },
      width: chartRef.current.clientWidth,
      height: 280,
    });
    const series = c.addSeries(CandlestickSeries, {});
    series.setData(
      chart.bars.map((b) => ({
        time: (Date.parse(b.ts) / 1000) as UTCTimestamp,
        open: b.open,
        high: b.high,
        low: b.low,
        close: b.close,
      })),
    );
    chartApi.current = c;
    return () => {
      c.remove();
      chartApi.current = null;
    };
  }, [chart]);

  async function pause() {
    await apiFetch(`/api/v1/live-lab/forward-tests/${runId}/pause`, { method: "POST" });
    load();
  }

  async function resume() {
    await apiFetch(`/api/v1/live-lab/forward-tests/${runId}/resume`, { method: "POST" });
    load();
  }

  if (!detail) {
    return <p className="text-sm text-zinc-500">Loading run…</p>;
  }

  const r = detail.run;

  return (
    <div className="space-y-5 pb-24">
      <header>
        <h1 className="page-title text-xl font-semibold text-white">{r.strategy_name}</h1>
        <p className="text-sm text-zinc-400">
          {r.symbol} {r.timeframe} · {r.research_state.replaceAll("_", " ")}
          {r.experimental ? " · experimental" : ""}
        </p>
        {r.strategy_phase && (
          <p className="mt-1 text-xs text-amber-200/80">
            Strategy phase: {r.strategy_phase.replaceAll("_", " ")}
            {r.runner_state_version ? ` · state v${r.runner_state_version}` : ""}
          </p>
        )}
      </header>

      <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
        <Stat label="Paper equity" value={`$${(chart?.run.equity ?? r.equity).toFixed(2)}`} />
        <Stat label="Net P&amp;L" value={`$${(chart?.run.net_pnl ?? r.net_pnl).toFixed(2)}`} />
        <Stat label="Trades" value={String(chart?.run.trade_count ?? r.trade_count)} />
        <Stat label="Pending" value={String(chart?.pending_orders?.length ?? 0)} />
      </div>

      <div ref={chartRef} className="w-full overflow-hidden rounded-lg border border-zinc-800" />

      {chart?.open_position && (
        <p className="text-xs text-cyan-200/80">Open position (persisted runner state) — see ledger for fills.</p>
      )}

      <div className="flex gap-2">
        <Button variant="secondary" onClick={pause}>
          Pause
        </Button>
        <Button onClick={resume}>Resume</Button>
      </div>

      <section>
        <h2 className="mb-2 text-sm font-semibold text-zinc-200">Equity (from ledger)</h2>
        <ul className="flex flex-wrap gap-2 text-xs text-zinc-400">
          {(chart?.equity_curve ?? []).slice(-8).map((p, i) => (
            <li key={i} className="rounded border border-zinc-800 px-2 py-1">
              ${p.equity.toFixed(0)}
            </li>
          ))}
        </ul>
      </section>

      <section>
        <h2 className="mb-2 text-sm font-semibold text-zinc-200">Trade journal</h2>
        <ul className="max-h-[40vh] space-y-2 overflow-y-auto text-xs">
          {detail.ledger.map((e) => (
            <li key={e.sequence} className="rounded border border-zinc-800 bg-zinc-950/40 p-2">
              <p className="font-medium text-cyan-300/90">{e.event_type}</p>
              <pre className="mt-1 overflow-x-auto text-[10px] text-zinc-400">{JSON.stringify(e.payload)}</pre>
            </li>
          ))}
        </ul>
      </section>
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