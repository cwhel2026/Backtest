"use client";

import Link from "next/link";
import { FormEvent, useEffect, useState } from "react";
import { apiFetch } from "@/lib/api";

type Job = {
  id: string;
  kind: string;
  status: string;
  title: string;
  message: string;
  progress_pct: number;
  created_at: string;
};

type Instrument = { id: string; symbol: string; name: string };
type Dataset = { id: string; timeframe: string; row_count: number; meta?: { label?: string } };

type OverviewStats = { ai_research_enabled: boolean; ai_configured: boolean };

export default function ResearchPage() {
  const [jobs, setJobs] = useState<Job[]>([]);
  const [instruments, setInstruments] = useState<Instrument[]>([]);
  const [datasets, setDatasets] = useState<Dataset[]>([]);
  const [aiStatus, setAiStatus] = useState<OverviewStats | null>(null);
  const [symbol, setSymbol] = useState("MES");
  const [timeframe, setTimeframe] = useState("5m");
  const [prompt, setPrompt] = useState("Opening range breakout with tight risk");
  const [datasetId, setDatasetId] = useState("");
  const [formMessage, setFormMessage] = useState<string | null>(null);

  useEffect(() => {
    const load = () => apiFetch<Job[]>("/api/v1/research/jobs?limit=50").then(setJobs);
    load();
    const t = setInterval(load, 5000);
    return () => clearInterval(t);
  }, []);

  useEffect(() => {
    Promise.all([
      apiFetch<Instrument[]>("/api/v1/instruments"),
      apiFetch<Dataset[]>("/api/v1/market-data/datasets"),
      apiFetch<OverviewStats>("/api/v1/overview/stats"),
    ]).then(([i, d, s]) => {
      setInstruments(i);
      setDatasets(d);
      setAiStatus(s);
      if (d.length && !datasetId) setDatasetId(d[0].id);
    });
  }, [datasetId]);

  async function onGenerate(e: FormEvent) {
    e.preventDefault();
    setFormMessage(null);
    try {
      const res = await apiFetch<{ job_id: string; mode: string }>("/api/v1/research/ai/generate", {
        method: "POST",
        body: JSON.stringify({
          instrument_symbol: symbol,
          timeframe,
          prompt,
          dataset_id: datasetId || null,
        }),
      });
      setFormMessage(
        `Queued (${res.mode === "openai" ? "OpenAI" : "built-in heuristic"}). Job ${res.job_id.slice(0, 8)}…`
      );
    } catch (err) {
      setFormMessage(String(err));
    }
  }

  const aiLabel = aiStatus?.ai_configured
    ? "OpenAI enabled"
    : aiStatus?.ai_research_enabled
      ? "Add OPENAI_API_KEY on backend"
      : "Heuristic mode (set AI_RESEARCH_ENABLED=true + OPENAI_API_KEY for GPT)";

  return (
    <div className="space-y-8">
      <div>
        <h2 className="page-title">Live research monitor</h2>
        <p className="page-sub">Background jobs from Celery workers (refreshes every 5s).</p>
      </div>

      <section className="rounded-lg border border-zinc-800 bg-[#181b22] p-4 md:p-6">
        <h3 className="text-sm font-medium text-zinc-200">Generate strategy (Phase 3)</h3>
        <p className="mt-1 text-xs text-zinc-500">{aiLabel}. Creates a DSL strategy and optional backtest.</p>
        <form onSubmit={onGenerate} className="mt-4 flex flex-col gap-3">
          <div className="flex flex-col gap-3 md:flex-row md:flex-wrap">
            <label className="flex w-full flex-col gap-1 text-sm text-zinc-400 md:w-auto">
              Instrument
              <select
                className="w-full rounded-md border border-zinc-700 bg-zinc-900 px-3 py-2.5 md:py-1"
                value={symbol}
                onChange={(e) => setSymbol(e.target.value)}
              >
                {instruments.map((i) => (
                  <option key={i.id} value={i.symbol}>
                    {i.symbol}
                  </option>
                ))}
              </select>
            </label>
            <label className="flex w-full flex-col gap-1 text-sm text-zinc-400 md:w-auto">
              Timeframe
              <select
                className="w-full rounded-md border border-zinc-700 bg-zinc-900 px-3 py-2.5 md:py-1"
                value={timeframe}
                onChange={(e) => setTimeframe(e.target.value)}
              >
                <option value="5m">5m</option>
                <option value="1m">1m</option>
                <option value="15m">15m</option>
                <option value="1h">1h</option>
              </select>
            </label>
            <label className="flex w-full flex-col gap-1 text-sm text-zinc-400 md:flex-1">
              Backtest dataset
              <select
                className="w-full rounded-md border border-zinc-700 bg-zinc-900 px-3 py-2.5 md:py-1"
                value={datasetId}
                onChange={(e) => setDatasetId(e.target.value)}
              >
                <option value="">Skip backtest</option>
                {datasets.map((d) => (
                  <option key={d.id} value={d.id}>
                    {d.timeframe} · {d.row_count} bars · {d.id.slice(0, 8)}
                  </option>
                ))}
              </select>
            </label>
          </div>
          <label className="flex flex-col gap-1 text-sm text-zinc-400">
            Research prompt
            <textarea
              className="min-h-[80px] rounded-md border border-zinc-700 bg-zinc-900 px-3 py-2 text-sm text-zinc-100"
              value={prompt}
              onChange={(e) => setPrompt(e.target.value)}
              placeholder="Describe entry logic, session, risk idea…"
            />
          </label>
          <button
            type="submit"
            className="w-full rounded-md bg-emerald-700 px-4 py-3 text-sm text-white hover:bg-emerald-600 md:w-auto md:py-2"
          >
            Generate &amp; queue
          </button>
        </form>
        {formMessage ? <p className="mt-3 text-sm text-zinc-400">{formMessage}</p> : null}
        <p className="mt-2 text-xs text-zinc-600">
          New strategies appear under{" "}
          <Link href="/strategies" className="text-emerald-500">
            Strategy Explorer
          </Link>
          .
        </p>
      </section>

      <div className="space-y-3">
        {jobs.length === 0 ? (
          <p className="text-zinc-500">No jobs in queue.</p>
        ) : (
          jobs.map((j) => (
            <div key={j.id} className="rounded-lg border border-zinc-800 bg-[#181b22] p-4">
              <div className="flex items-center justify-between gap-4">
                <p className="font-medium text-zinc-100">{j.title}</p>
                <span className="text-xs text-zinc-400">
                  {j.status} · {j.kind}
                </span>
              </div>
              <p className="mt-2 text-sm text-zinc-500">{j.message}</p>
              <ProgressBar pct={j.progress_pct} />
            </div>
          ))
        )}
      </div>
    </div>
  );
}

function ProgressBar({ pct }: { pct: number }) {
  return (
    <div className="mt-3 h-1.5 w-full overflow-hidden rounded bg-zinc-800">
      <div className="h-full bg-emerald-500 transition-all" style={{ width: `${pct}%` }} />
    </div>
  );
}