"use client";

import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  CandlestickSeries,
  LineSeries,
  createChart,
  createSeriesMarkers,
  type IChartApi,
  type UTCTimestamp,
} from "lightweight-charts";
import { apiFetch } from "@/lib/api";

type DecisionEvent = {
  ts: string;
  bar_index: number;
  event_type: string;
  explanation: string;
  rule_id: string;
  source: string;
  levels?: Record<string, unknown>;
  setup_id?: string;
  direction?: string | null;
};

type DebuggerBar = {
  bar_index: number;
  ts: string;
  open: number;
  high: number;
  low: number;
  close: number;
  volume: number;
};

type OhlcBar = { ts: string; open: number; high: number; low: number; close: number; volume: number };

type SimLog = {
  decision_events: DecisionEvent[];
  rejected_setups: { reason_code: string; explanation: string; ts: string }[];
  simulation_provenance: Record<string, unknown>;
  engine_version?: string;
};

type Trade = { trade_number: number; signal_ts: string; meta?: Record<string, unknown> };

export default function StrategyDebuggerPage() {
  const params = useSearchParams();
  const runId = params.get("run_id") || "";
  const [sim, setSim] = useState<SimLog | null>(null);
  const [bars, setBars] = useState<DebuggerBar[]>([]);
  const [bars4h, setBars4h] = useState<OhlcBar[]>([]);
  const [trades, setTrades] = useState<Trade[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [tradeNum, setTradeNum] = useState<number | null>(null);
  const [replayIdx, setReplayIdx] = useState(0);
  const [playing, setPlaying] = useState(false);
  const [speed, setSpeed] = useState(1);
  const [selectedEvent, setSelectedEvent] = useState<number | null>(null);
  const chartRef = useRef<HTMLDivElement>(null);
  const chart4hRef = useRef<HTMLDivElement>(null);
  const chartApi = useRef<IChartApi | null>(null);

  useEffect(() => {
    if (!runId) return;
    setError(null);
    Promise.all([
      apiFetch<SimLog>(`/api/v1/backtests/${runId}/simulation-log`).catch((e) => {
        setError(String(e));
        return null;
      }),
      apiFetch<Trade[]>(`/api/v1/backtests/${runId}/trades`),
    ]).then(([log, t]) => {
      if (log) setSim(log);
      setTrades(t);
      if (t.length) setTradeNum(t[0].trade_number);
    });
  }, [runId]);

  const loadBars = useCallback(
    async (tn: number | null) => {
      if (!runId) return;
      const q = tn != null ? `?trade_number=${tn}&padding=100&limit=800` : "?limit=800";
      const data = await apiFetch<DebuggerBar[]>(`/api/v1/backtests/${runId}/debugger/bars${q}`);
      setBars(data);
      setReplayIdx(0);
    },
    [runId],
  );

  useEffect(() => {
    loadBars(tradeNum);
  }, [tradeNum, loadBars]);

  useEffect(() => {
    if (!runId) return;
    const berg = (sim?.simulation_provenance?.entry_type as string) === "berg_tnb_model_v1";
    if (!berg && sim?.decision_events?.every((e) => !e.rule_id?.startsWith("berg"))) return;
    apiFetch<OhlcBar[]>(`/api/v1/backtests/${runId}/debugger/bars-4h?limit=300`)
      .then(setBars4h)
      .catch(() => setBars4h([]));
  }, [runId, sim]);

  const visibleEvents = useMemo(() => {
    if (!sim?.decision_events) return [];
    const lastBar = bars[Math.min(replayIdx, Math.max(0, bars.length - 1))];
    if (!lastBar) return [];
    const cutoff = lastBar.bar_index;
    return sim.decision_events.filter((e) => e.bar_index >= 0 && e.bar_index <= cutoff);
  }, [sim, bars, replayIdx]);

  const chartBars = useMemo(() => bars.slice(0, replayIdx + 1), [bars, replayIdx]);

  const levelOverlays = useMemo(() => {
    const out: { key: string; value: number; color: string }[] = [];
    const pick = (field: string) => {
      for (let i = visibleEvents.length - 1; i >= 0; i -= 1) {
        const raw = visibleEvents[i].levels?.[field];
        if (raw != null && raw !== "") return Number(raw);
      }
      return null;
    };
    const limit = pick("limit");
    const stop = pick("stop");
    const target = pick("target");
    const liq = pick("liquidity_level");
    if (limit != null) out.push({ key: "limit", value: limit, color: "#fbbf24" });
    if (stop != null) out.push({ key: "stop", value: stop, color: "#f87171" });
    if (target != null) out.push({ key: "target", value: target, color: "#34d399" });
    if (liq != null) out.push({ key: "session", value: liq, color: "#818cf8" });
    return out;
  }, [visibleEvents]);

  useEffect(() => {
    if (!playing || !bars.length) return;
    const ms = Math.max(80, 400 / speed);
    const id = window.setInterval(() => {
      setReplayIdx((r) => (r >= bars.length - 1 ? r : r + 1));
    }, ms);
    return () => window.clearInterval(id);
  }, [playing, speed, bars.length]);

  useEffect(() => {
    const host = chartRef.current;
    if (!host || !chartBars.length) return;
    const chart = createChart(host, {
      layout: { background: { color: "#0e1015" }, textColor: "#a1a1aa" },
      grid: { vertLines: { color: "#1f2128" }, horzLines: { color: "#1f2128" } },
      width: host.clientWidth,
      height: 420,
      timeScale: { timeVisible: true, secondsVisible: false },
    });
    chartApi.current = chart;
    const series = chart.addSeries(CandlestickSeries, {
      upColor: "#34d399",
      downColor: "#f87171",
      borderVisible: false,
      wickUpColor: "#34d399",
      wickDownColor: "#f87171",
    });
    const data = chartBars.map((b) => ({
      time: Math.floor(new Date(b.ts).getTime() / 1000) as UTCTimestamp,
      open: b.open,
      high: b.high,
      low: b.low,
      close: b.close,
    }));
    series.setData(data);
    for (const layer of levelOverlays) {
      const ls = chart.addSeries(LineSeries, {
        color: layer.color,
        lineWidth: 1,
        lineStyle: layer.key === "limit" ? 2 : 0,
        title: layer.key,
      });
      ls.setData(
        data.map((row) => ({
          time: row.time,
          value: layer.value,
        })),
      );
    }
    const markers = visibleEvents
      .filter(
        (e) =>
          e.event_type.includes("SWEEP") ||
          e.event_type.includes("BOS") ||
          e.event_type.includes("FIB") ||
          e.event_type.includes("ORDER") ||
          e.event_type.includes("SESSION"),
      )
      .map((e) => ({
        time: Math.floor(new Date(e.ts).getTime() / 1000) as UTCTimestamp,
        position: "belowBar" as const,
        color: "#60a5fa",
        shape: "circle" as const,
        text: e.event_type.replace(/_/g, " ").slice(0, 12),
      }));
    createSeriesMarkers(series, markers);
    chart.timeScale().fitContent();
    const onResize = () => chart.applyOptions({ width: host.clientWidth });
    window.addEventListener("resize", onResize);
    return () => {
      window.removeEventListener("resize", onResize);
      chart.remove();
    };
  }, [chartBars, visibleEvents, levelOverlays]);

  useEffect(() => {
    const host = chart4hRef.current;
    if (!host || !bars4h.length) return;
    const chart = createChart(host, {
      layout: { background: { color: "#0e1015" }, textColor: "#a1a1aa" },
      grid: { vertLines: { color: "#1f2128" }, horzLines: { color: "#1f2128" } },
      width: host.clientWidth,
      height: 180,
      timeScale: { timeVisible: true, secondsVisible: false },
    });
    const series = chart.addSeries(CandlestickSeries, {
      upColor: "#64748b",
      downColor: "#475569",
      borderVisible: false,
      wickUpColor: "#64748b",
      wickDownColor: "#475569",
    });
    const biasMarkers = (sim?.decision_events ?? [])
      .filter((e) => e.event_type === "BIAS_CONFIRMED" && e.bar_index <= (bars[replayIdx]?.bar_index ?? 1e9))
      .map((e) => ({
        time: Math.floor(new Date(e.ts).getTime() / 1000) as UTCTimestamp,
        position: "aboveBar" as const,
        color: "#a78bfa",
        shape: "square" as const,
        text: "4H bias",
      }));
    series.setData(
      bars4h.map((b) => ({
        time: Math.floor(new Date(b.ts).getTime() / 1000) as UTCTimestamp,
        open: b.open,
        high: b.high,
        low: b.low,
        close: b.close,
      })),
    );
    if (biasMarkers.length) createSeriesMarkers(series, biasMarkers);
    chart.timeScale().fitContent();
    const onResize = () => chart.applyOptions({ width: host.clientWidth });
    window.addEventListener("resize", onResize);
    return () => {
      window.removeEventListener("resize", onResize);
      chart.remove();
    };
  }, [bars4h, sim, bars, replayIdx]);

  function jumpToEvent(idx: number) {
    const ev = sim?.decision_events[idx];
    if (!ev || !bars.length) return;
    const bi = bars.findIndex((b) => b.bar_index === ev.bar_index);
    if (bi >= 0) setReplayIdx(bi);
    setSelectedEvent(idx);
  }

  if (!runId) {
    return (
      <div className="mx-auto max-w-2xl space-y-4 p-6">
        <h1 className="text-xl font-semibold text-white">Strategy Debugger</h1>
        <p className="text-zinc-400">
          Open a completed backtest from{" "}
          <Link href="/backtests" className="text-emerald-400 underline">
            Backtests
          </Link>{" "}
          and append <code className="text-zinc-300">?run_id=&lt;uuid&gt;</code> to this URL, or add a link from the
          run detail page.
        </p>
      </div>
    );
  }

  return (
    <div className="-mx-4 flex flex-col gap-4 md:mx-0">
      <header className="flex flex-wrap items-end justify-between gap-3 border-b border-[var(--border)] px-4 pb-4 md:px-0">
        <div>
          <p className="text-[10px] font-semibold tracking-[0.2em] text-[var(--accent)]">STRATEGY FIDELITY</p>
          <h1 className="page-title">Visual Debugger</h1>
          <p className="text-xs text-zinc-500">Run {runId.slice(0, 8)}… · replay driven by persisted simulation events</p>
        </div>
        {trades.length > 0 && (
          <label className="text-sm text-zinc-400">
            Trade{" "}
            <select
              className="min-h-[44px] rounded-xl border border-[var(--border)] bg-[var(--card-elevated)] px-3 py-2 text-zinc-100"
              value={tradeNum ?? ""}
              onChange={(e) => setTradeNum(Number(e.target.value))}
            >
              {trades.map((t) => (
                <option key={t.trade_number} value={t.trade_number}>
                  #{t.trade_number}
                </option>
              ))}
            </select>
          </label>
        )}
      </header>

      {error && (
        <div className="rounded-lg border border-amber-900/50 bg-amber-950/30 p-4 text-amber-200">{error}</div>
      )}

      {bars4h.length > 0 && (
        <div>
          <p className="mb-1 text-xs text-zinc-500">4H bias context (markers only after confirmation in replay)</p>
          <div ref={chart4hRef} className="h-[200px] w-full rounded-xl border border-[var(--border)] bg-[var(--shell-nav)] sm:h-[240px]" />
        </div>
      )}
      <p className="text-xs text-zinc-500">5m execution · fib/limit/stop/target lines from visible events only</p>
      <div ref={chartRef} className="h-[min(52vh,420px)] w-full rounded-xl border border-[var(--border)] bg-[var(--shell-nav)]" />

      <div className="sticky bottom-[calc(72px+env(safe-area-inset-bottom,0px))] z-20 flex flex-wrap items-center gap-2 rounded-2xl border border-[var(--border)] bg-[var(--card)]/95 p-3 backdrop-blur md:bottom-4">
        <button
          type="button"
          className="min-h-[44px] min-w-[44px] rounded-xl bg-[var(--card-elevated)] px-4 text-sm font-medium"
          onClick={() => setReplayIdx((r) => Math.max(0, r - 1))}
        >
          Prev
        </button>
        <button
          type="button"
          className="min-h-[44px] min-w-[44px] rounded-xl bg-[var(--card-elevated)] px-4 text-sm font-medium"
          onClick={() => setReplayIdx((r) => Math.min(bars.length - 1, r + 1))}
        >
          Next
        </button>
        <button
          type="button"
          className="min-h-[44px] flex-1 rounded-xl bg-[var(--accent)] px-4 text-sm font-semibold text-[#041018] sm:flex-none"
          onClick={() => setPlaying((p) => !p)}
        >
          {playing ? "Pause" : "Play"}
        </button>
        <label className="flex min-h-[44px] flex-1 basis-full items-center gap-2 text-xs text-zinc-400 sm:basis-auto">
          Speed
          <input
            type="range"
            min={0.5}
            max={4}
            step={0.5}
            value={speed}
            onChange={(e) => setSpeed(Number(e.target.value))}
            className="flex-1"
          />
        </label>
        <button
          type="button"
          className="min-h-[44px] rounded-xl bg-[var(--card-elevated)] px-3 text-sm"
          onClick={() => setReplayIdx(0)}
        >
          Reset
        </button>
        <span className="w-full text-center text-xs text-zinc-500 sm:ml-auto sm:w-auto sm:text-right">
          Bar {bars[replayIdx]?.bar_index ?? "—"} / {bars.length ? bars[bars.length - 1].bar_index : "—"}
        </span>
      </div>

      <div className="grid gap-4 lg:grid-cols-2">
        <div className="max-h-80 overflow-y-auto rounded-lg border border-zinc-800 bg-zinc-900/30 p-3">
          <h2 className="mb-2 text-sm font-medium text-zinc-200">Event timeline (visible through replay)</h2>
          <ul className="space-y-1 text-xs">
            {visibleEvents.map((e, i) => (
              <li key={`${e.ts}-${e.rule_id}-${i}`}>
                <button
                  type="button"
                  className={`w-full rounded px-2 py-1 text-left hover:bg-zinc-800 ${
                    selectedEvent === i ? "bg-zinc-800" : ""
                  }`}
                  onClick={() => jumpToEvent(sim!.decision_events.indexOf(e))}
                >
                  <span className="text-emerald-400">{e.event_type}</span>{" "}
                  <span className="text-zinc-500">@{e.bar_index}</span> — {e.explanation}
                  <span className="ml-1 text-zinc-600">[{e.source}]</span>
                </button>
              </li>
            ))}
            {!visibleEvents.length && <li className="text-zinc-500">No events yet for this replay frame.</li>}
          </ul>
        </div>

        <div className="max-h-80 overflow-y-auto rounded-lg border border-zinc-800 bg-zinc-900/30 p-3">
          <h2 className="mb-2 text-sm font-medium text-zinc-200">Rejected setups</h2>
          <ul className="space-y-1 text-xs text-zinc-300">
            {(sim?.rejected_setups ?? []).map((r, i) => (
              <li key={i} className="rounded border border-zinc-800/80 p-2">
                <span className="text-amber-400">{r.reason_code}</span> — {r.explanation}
              </li>
            ))}
            {!sim?.rejected_setups?.length && <li className="text-zinc-500">No rejected candidate setups recorded.</li>}
          </ul>
          {sim?.simulation_provenance && (
            <pre className="mt-3 overflow-x-auto rounded bg-black/40 p-2 text-[10px] text-zinc-500">
              {JSON.stringify(sim.simulation_provenance, null, 2)}
            </pre>
          )}
        </div>
      </div>
    </div>
  );
}