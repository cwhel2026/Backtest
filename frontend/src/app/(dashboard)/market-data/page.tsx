"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import {
  CandlestickSeries,
  createChart,
  type IChartApi,
  type UTCTimestamp,
} from "lightweight-charts";
import { apiFetch } from "@/lib/api";

type Provider = { slug: string; display_name: string; state: string; message: string };
type Instrument = { id: string; symbol: string; name: string };
type Dataset = {
  id: string;
  timeframe: string;
  row_count: number;
  validation_status: string;
  quality_class?: string | null;
  data_lineage?: string | null;
  genuine_for_research?: boolean | null;
  data_lineage_label?: string | null;
  coverage_start: string | null;
  coverage_end: string | null;
  version_tag: string;
  content_checksum?: string | null;
  meta?: Record<string, unknown>;
};

type ProviderComparison = {
  micro_contracts: string[];
  providers: { id: string; name: string; genuine_for_research: boolean; typical_cost_gbp_month_note: string }[];
  estimates?: { available: boolean; note?: string; symbols?: Record<string, unknown> };
};

type Budget = {
  month: string;
  budget_gbp: number;
  estimated_usd: number;
  approved_usd: number;
  actual_usd: number;
  remaining_budget_gbp: number;
  gbp_usd_rate: number | null;
};

type OhlcvBar = { ts: string; open: number; high: number; low: number; close: number; volume: number };

type Readiness = {
  dataset_id: string;
  quality_class: string;
  video_readiness: Record<string, { ready?: boolean; reason?: string }>;
  backtest_allowed: boolean;
};

type EngineHealth = {
  database: { async_ok: boolean; sync_ok: boolean; sync_detail: string };
  storage: {
    writable: boolean;
    writable_detail: string;
    persistent_ok: boolean;
    persistent_detail: string;
    resolved_path: string;
    railway_volume_mounted?: boolean;
    recommended_path?: string;
    s3_ok?: boolean;
    s3_detail?: string;
    s3_mirror_configured?: boolean;
    boot?: Record<string, unknown>;
  };
  databento: { configured: boolean; live_smoke_enabled: boolean };
  datasets: { count_recent: number; ready: number; blocked: number };
};

export default function HistoricalDataPage() {
  const [providers, setProviders] = useState<Provider[]>([]);
  const [instruments, setInstruments] = useState<Instrument[]>([]);
  const [datasets, setDatasets] = useState<Dataset[]>([]);
  const [budget, setBudget] = useState<Budget | null>(null);
  const [symbol, setSymbol] = useState("MES");
  const [ingestTf, setIngestTf] = useState("5m");
  const [ingestProvider, setIngestProvider] = useState("databento");
  const [daysBack, setDaysBack] = useState(14);
  const [estimate, setEstimate] = useState<Record<string, unknown> | null>(null);
  const [confirmPaid, setConfirmPaid] = useState(false);
  const [message, setMessage] = useState<string | null>(null);
  const [selectedDataset, setSelectedDataset] = useState<string>("");
  const [quality, setQuality] = useState<Record<string, unknown> | null>(null);
  const [readiness, setReadiness] = useState<Readiness | null>(null);
  const [health, setHealth] = useState<EngineHealth | null>(null);
  const [comparison, setComparison] = useState<ProviderComparison | null>(null);
  const chartRef = useRef<HTMLDivElement>(null);
  const chartApi = useRef<IChartApi | null>(null);

  const reload = useCallback(() => {
    return Promise.all([
      apiFetch<Provider[]>("/api/v1/market-data/providers"),
      apiFetch<Instrument[]>("/api/v1/instruments"),
      apiFetch<Dataset[]>("/api/v1/market-data/datasets"),
      apiFetch<Budget>("/api/v1/market-data/budget"),
      apiFetch<EngineHealth>("/api/v1/market-data/health"),
      apiFetch<ProviderComparison>("/api/v1/market-data/provider-comparison?days=14"),
    ]).then(([p, i, d, b, h, cmp]) => {
      setProviders(p);
      setInstruments(i);
      setDatasets(d);
      setBudget(b);
      setHealth(h);
      setComparison(cmp);
      if (d.length && !selectedDataset) setSelectedDataset(d[0].id);
    });
  }, [selectedDataset]);

  useEffect(() => {
    reload();
  }, [reload]);

  async function fetchEstimate() {
    setMessage(null);
    const end = new Date();
    const start = new Date(end.getTime() - daysBack * 86400000);
    try {
      const est = await apiFetch<Record<string, unknown>>("/api/v1/market-data/ingest/estimate-range", {
        method: "POST",
        body: JSON.stringify({
          provider_slug: ingestProvider,
          instrument_symbol: symbol,
          timeframe: ingestTf,
          start: start.toISOString(),
          end: end.toISOString(),
        }),
      });
      setEstimate(est);
    } catch (e) {
      setMessage(String(e));
    }
  }

  async function queueIngestion() {
    setMessage(null);
    const end = new Date();
    const start = new Date(end.getTime() - daysBack * 86400000);
    const estUsd = estimate?.estimated_usd;
    try {
      const res = await apiFetch<{ job_id?: string; status: string; dataset_id?: string; message?: string }>(
        "/api/v1/market-data/ingest",
        {
          method: "POST",
          body: JSON.stringify({
            provider_slug: ingestProvider,
            instrument_symbol: symbol,
            timeframe: ingestTf,
            start: start.toISOString(),
            end: end.toISOString(),
            confirm_paid: confirmPaid || ingestProvider === "yahoo",
            approved_cost_usd: typeof estUsd === "number" ? estUsd : undefined,
          }),
        }
      );
      if (res.status === "cached" && res.dataset_id) {
        setMessage(res.message || `Using cached dataset ${res.dataset_id.slice(0, 8)}`);
      } else {
        setMessage(`Job ${res.job_id?.slice(0, 8)} queued. Track progress under Live Research → Jobs.`);
      }
      await reload();
    } catch (e) {
      setMessage(String(e));
    }
  }

  async function loadQuality(dsId: string) {
    const [q, r] = await Promise.all([
      apiFetch<Record<string, unknown>>(`/api/v1/market-data/datasets/${dsId}/quality`),
      apiFetch<Readiness>(`/api/v1/market-data/datasets/${dsId}/readiness`),
    ]);
    setQuality(q);
    setReadiness(r);
  }

  useEffect(() => {
    if (!selectedDataset) return;
    loadQuality(selectedDataset);
  }, [selectedDataset]);

  useEffect(() => {
    const host = chartRef.current;
    if (!host || !selectedDataset) return;
    const chart = createChart(host, {
      layout: { background: { color: "#181b22" }, textColor: "#a1a1aa" },
      grid: { vertLines: { color: "#27272a" }, horzLines: { color: "#27272a" } },
      width: host.clientWidth,
      height: 320,
      timeScale: { timeVisible: true },
    });
    chartApi.current = chart;
    const series = chart.addSeries(CandlestickSeries, {
      upColor: "#34d399",
      downColor: "#f87171",
      borderVisible: false,
      wickUpColor: "#34d399",
      wickDownColor: "#f87171",
    });
    let cancelled = false;
    apiFetch<OhlcvBar[]>(`/api/v1/market-data/datasets/${selectedDataset}/bars?limit=1200`).then((bars) => {
      if (cancelled) return;
      series.setData(
        bars.map((b) => ({
          time: Math.floor(new Date(b.ts).getTime() / 1000) as UTCTimestamp,
          open: b.open,
          high: b.high,
          low: b.low,
          close: b.close,
        }))
      );
      chart.timeScale().fitContent();
    });
    return () => {
      cancelled = true;
      chart.remove();
    };
  }, [selectedDataset]);

  return (
    <div className="space-y-8">
      <header>
        <h2 className="page-title">Historical Data</h2>
        <p className="page-sub">
          Phase 2 — licensed Databento 1m primary (£0–£50 budget). Synthetic/free feeds blocked for genuine backtests.
        </p>
      </header>

      {comparison ? (
        <section className="rounded-lg border border-zinc-800 bg-[#181b22] p-4">
          <h3 className="text-sm font-medium text-zinc-200">MNQ / MES / MGC providers</h3>
          <p className="mt-1 text-xs text-zinc-500">
            Recommended: Databento 1m → derive 5m/4H locally. Live cost when{" "}
            <code className="text-zinc-400">DATABENTO_API_KEY</code> is set on the server.
          </p>
          <div className="mt-3 overflow-x-auto">
            <table className="w-full text-left text-xs">
              <thead className="text-zinc-500">
                <tr>
                  <th className="px-2 py-1">Provider</th>
                  <th className="px-2 py-1">Genuine research</th>
                  <th className="px-2 py-1">Cost notes</th>
                </tr>
              </thead>
              <tbody>
                {comparison.providers.map((pr) => (
                  <tr key={pr.id} className="border-t border-zinc-800">
                    <td className="px-2 py-2 text-zinc-200">{pr.name}</td>
                    <td className="px-2 py-2">{pr.genuine_for_research ? "Yes" : "No"}</td>
                    <td className="px-2 py-2 text-zinc-400">{pr.typical_cost_gbp_month_note}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          {comparison.estimates && !comparison.estimates.available && (
            <p className="mt-2 text-xs text-amber-400/90">{comparison.estimates.note}</p>
          )}
        </section>
      ) : null}

      {health ? (
        <section className="rounded-lg border border-zinc-800 bg-[#181b22] p-4">
          <h3 className="text-sm font-medium text-zinc-200">Engine health</h3>
          <ul className="mt-2 grid gap-2 text-sm text-zinc-400 sm:grid-cols-2">
            <li>
              Database: {health.database.async_ok && health.database.sync_ok ? "ok" : "degraded"} (
              {health.database.sync_detail})
            </li>
            <li>
              Parquet store: {health.storage.writable ? "writable" : "fail"} ·{" "}
              {health.storage.persistent_ok ? "persistent" : "ephemeral risk"} — {health.storage.resolved_path}
              {health.storage.railway_volume_mounted === false ? " · /data not mounted" : ""}
            </li>
            <li>
              S3 mirror: {health.storage.s3_mirror_configured ? health.storage.s3_ok ? "ok" : "fail" : "off"}
              {health.storage.s3_detail ? ` — ${health.storage.s3_detail}` : ""}
            </li>
            <li>Recommended Railway path: {health.storage.recommended_path ?? "/data/ohlcv"}</li>
            <li>Databento: {health.databento.configured ? "key set" : "not configured"}</li>
            <li>
              Datasets (recent): {health.datasets.ready} ready · {health.datasets.blocked} blocked
            </li>
          </ul>
        </section>
      ) : null}

      {budget ? (
        <section className="grid gap-3 sm:grid-cols-4">
          <Stat label="Monthly budget (GBP)" value={`£${budget.budget_gbp.toFixed(2)}`} />
          <Stat label="Approved USD" value={`$${budget.approved_usd.toFixed(2)}`} />
          <Stat label="Actual USD" value={`$${budget.actual_usd.toFixed(2)}`} />
          <Stat label="Remaining (GBP)" value={`£${budget.remaining_budget_gbp.toFixed(2)}`} />
        </section>
      ) : null}

      <section className="rounded-lg border border-zinc-800 bg-[#181b22] p-4 md:p-6">
        <h3 className="text-sm font-medium text-zinc-200">Download manager</h3>
        <p className="mt-1 text-xs text-zinc-500">
          MNQ · MES · MGC via Databento continuous symbols (e.g. MES.c.0) — not back-adjusted stitched prices.
        </p>
        <div className="mt-4 grid gap-3 md:grid-cols-2 lg:grid-cols-4">
          <Field label="Instrument">
            <select
              className="w-full rounded-md border border-zinc-700 bg-zinc-900 px-3 py-2"
              value={symbol}
              onChange={(e) => setSymbol(e.target.value)}
            >
              {instruments.map((i) => (
                <option key={i.id} value={i.symbol}>
                  {i.symbol}
                </option>
              ))}
            </select>
          </Field>
          <Field label="Provider">
            <select
              className="w-full rounded-md border border-zinc-700 bg-zinc-900 px-3 py-2"
              value={ingestProvider}
              onChange={(e) => setIngestProvider(e.target.value)}
            >
              <option value="databento">Databento (primary)</option>
              <option value="yahoo">Yahoo (free / fallback)</option>
              <option value="finzdata">FinzData</option>
              <option value="ibkr">IBKR</option>
            </select>
          </Field>
          <Field label="Timeframe">
            <select
              className="w-full rounded-md border border-zinc-700 bg-zinc-900 px-3 py-2"
              value={ingestTf}
              onChange={(e) => setIngestTf(e.target.value)}
            >
              {["1m", "5m", "15m", "30m", "1h", "4h"].map((tf) => (
                <option key={tf} value={tf}>
                  {tf}
                </option>
              ))}
            </select>
          </Field>
          <Field label="History (days)">
            <input
              type="number"
              min={1}
              max={120}
              className="w-full rounded-md border border-zinc-700 bg-zinc-900 px-3 py-2"
              value={daysBack}
              onChange={(e) => setDaysBack(Number(e.target.value))}
            />
          </Field>
        </div>
        <div className="mt-4 flex flex-wrap gap-2">
          <button
            type="button"
            onClick={fetchEstimate}
            className="rounded-md border border-zinc-600 px-4 py-2 text-sm text-zinc-200 hover:bg-zinc-900"
          >
            Get cost estimate
          </button>
          <label className="flex items-center gap-2 text-sm text-zinc-400">
            <input type="checkbox" checked={confirmPaid} onChange={(e) => setConfirmPaid(e.target.checked)} />
            Approve paid download
          </label>
          <button
            type="button"
            onClick={queueIngestion}
            className="rounded-md bg-emerald-700 px-4 py-2 text-sm text-white hover:bg-emerald-600"
          >
            Queue download
          </button>
        </div>
        {estimate ? (
          <pre className="mt-3 overflow-auto rounded border border-zinc-800 bg-black/40 p-3 text-xs text-zinc-400">
            {JSON.stringify(estimate, null, 2)}
          </pre>
        ) : null}
        {message ? <p className="mt-3 text-sm text-zinc-400">{message}</p> : null}
      </section>

      <section className="rounded-lg border border-zinc-800 bg-[#181b22] p-4">
        <h3 className="text-sm font-medium text-zinc-200">Data library</h3>
        <div className="mt-3 overflow-x-auto">
          <table className="w-full text-left text-sm">
            <thead className="text-xs uppercase text-zinc-500">
              <tr>
                <th className="px-2 py-1">ID</th>
                <th className="px-2 py-1">TF</th>
                <th className="px-2 py-1">Bars</th>
                <th className="px-2 py-1">Quality</th>
                <th className="px-2 py-1">Lineage</th>
                <th className="px-2 py-1">Range</th>
                <th className="px-2 py-1">Version</th>
              </tr>
            </thead>
            <tbody>
              {datasets.map((d) => (
                <tr
                  key={d.id}
                  className={`cursor-pointer border-t border-zinc-800/80 ${selectedDataset === d.id ? "bg-zinc-900/60" : ""}`}
                  onClick={() => setSelectedDataset(d.id)}
                >
                  <td className="px-2 py-2 font-mono text-xs">{d.id.slice(0, 8)}</td>
                  <td className="px-2 py-2">{d.timeframe}</td>
                  <td className="px-2 py-2">{d.row_count}</td>
                  <td className="px-2 py-2">{d.quality_class || d.validation_status}</td>
                  <td className="px-2 py-2 text-xs">
                    {d.genuine_for_research ? (
                      <span className="text-emerald-400">Genuine</span>
                    ) : (
                      <span className="text-amber-500">{d.data_lineage || "legacy"}</span>
                    )}
                  </td>
                  <td className="px-2 py-2 text-xs text-zinc-500">
                    {d.coverage_start?.slice(0, 10)} → {d.coverage_end?.slice(0, 10)}
                  </td>
                  <td className="px-2 py-2 text-xs">{d.version_tag}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>

      <section className="grid gap-6 lg:grid-cols-2">
        <div className="rounded-lg border border-zinc-800 bg-[#181b22] p-4">
          <h3 className="text-sm font-medium text-zinc-200">Data quality</h3>
          {quality ? (
            <pre className="mt-2 max-h-64 overflow-auto text-xs text-zinc-400">{JSON.stringify(quality, null, 2)}</pre>
          ) : (
            <p className="mt-2 text-sm text-zinc-500">Select a dataset.</p>
          )}
        </div>
        <div className="rounded-lg border border-zinc-800 bg-[#181b22] p-4">
          <h3 className="text-sm font-medium text-zinc-200">Backtest readiness (video strategies)</h3>
          {readiness ? (
            <div className="mt-2 space-y-2 text-sm text-zinc-300">
              <p>Class: {readiness.quality_class} · Backtest allowed: {readiness.backtest_allowed ? "yes" : "no"}</p>
              <p>video_liquidity_sweep: {readiness.video_readiness.video_liquidity_sweep?.reason}</p>
              <p>video_anchor_bos: {readiness.video_readiness.video_anchor_bos?.reason}</p>
            </div>
          ) : (
            <p className="mt-2 text-sm text-zinc-500">Select a dataset.</p>
          )}
        </div>
      </section>

      <section>
        <h3 className="text-sm font-medium text-zinc-200">Data preview</h3>
        <div ref={chartRef} className="mt-2 w-full rounded-lg border border-zinc-800" />
      </section>

      <section>
        <h3 className="text-sm font-medium text-zinc-200">Providers</h3>
        <ul className="mt-2 space-y-2 text-sm text-zinc-400">
          {providers.map((p) => (
            <li key={p.slug}>
              <span className="text-zinc-200">{p.display_name}</span> — {p.state}: {p.message}
            </li>
          ))}
        </ul>
      </section>
    </div>
  );
}

function Stat({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-lg border border-zinc-800 bg-[#181b22] p-3">
      <p className="text-xs uppercase text-zinc-500">{label}</p>
      <p className="mt-1 text-lg text-white">{value}</p>
    </div>
  );
}

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <label className="flex flex-col gap-1 text-sm text-zinc-400">
      {label}
      {children}
    </label>
  );
}