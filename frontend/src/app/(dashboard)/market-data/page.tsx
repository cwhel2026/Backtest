"use client";

import { useEffect, useState } from "react";
import { apiFetch } from "@/lib/api";

type Provider = { slug: string; display_name: string; state: string; message: string };
type Instrument = { id: string; symbol: string; name: string };
type Dataset = {
  id: string;
  timeframe: string;
  row_count: number;
  validation_status: string;
  coverage_start: string | null;
  coverage_end: string | null;
};

export default function MarketDataPage() {
  const [providers, setProviders] = useState<Provider[]>([]);
  const [instruments, setInstruments] = useState<Instrument[]>([]);
  const [datasets, setDatasets] = useState<Dataset[]>([]);
  const [symbol, setSymbol] = useState("MES");
  const [message, setMessage] = useState<string | null>(null);

  useEffect(() => {
    Promise.all([
      apiFetch<Provider[]>("/api/v1/market-data/providers"),
      apiFetch<Instrument[]>("/api/v1/instruments"),
      apiFetch<Dataset[]>("/api/v1/market-data/datasets"),
    ]).then(([p, i, d]) => {
      setProviders(p);
      setInstruments(i);
      setDatasets(d);
    });
  }, []);

  async function queueIngestion() {
    setMessage(null);
    const end = new Date();
    const start = new Date(end.getTime() - 7 * 24 * 60 * 60 * 1000);
    try {
      const res = await apiFetch<{ job_id: string; status: string }>("/api/v1/market-data/ingest", {
        method: "POST",
        body: JSON.stringify({
          provider_slug: "databento",
          instrument_symbol: symbol,
          timeframe: "1m",
          start: start.toISOString(),
          end: end.toISOString(),
        }),
      });
      setMessage(`Job ${res.job_id} queued (${res.status}). Check Live Research for outcomes.`);
    } catch (e) {
      setMessage(String(e));
    }
  }

  return (
    <div className="space-y-8">
      <div>
        <h2 className="text-2xl font-semibold text-white">Market data</h2>
        <p className="mt-1 text-sm text-zinc-500">Provider status and dataset registry.</p>
      </div>

      <section className="rounded-lg border border-zinc-800 bg-[#181b22] p-6">
        <h3 className="text-sm font-medium text-zinc-300">Queue historical ingestion</h3>
        <p className="mt-1 text-xs text-zinc-500">
          Requires a licensed provider key. The worker records real job status — no synthetic bars.
        </p>
        <div className="mt-4 flex flex-wrap items-end gap-3">
          <label className="text-sm text-zinc-400">
            Instrument
            <select
              className="ml-2 rounded-md border border-zinc-700 bg-zinc-900 px-2 py-1"
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
          <button
            type="button"
            onClick={queueIngestion}
            className="rounded-md bg-emerald-700 px-4 py-2 text-sm text-white hover:bg-emerald-600"
          >
            Queue Databento ingestion (7d)
          </button>
        </div>
        {message ? <p className="mt-3 text-sm text-zinc-400">{message}</p> : null}
      </section>

      <section>
        <h3 className="text-sm font-medium text-zinc-300">Providers</h3>
        <ul className="mt-3 space-y-2">
          {providers.map((p) => (
            <li key={p.slug} className="rounded-md border border-zinc-800 px-4 py-3 text-sm">
              <span className="font-medium text-zinc-100">{p.display_name}</span>
              <span className="ml-2 text-zinc-500">— {p.message}</span>
            </li>
          ))}
        </ul>
      </section>

      <section>
        <h3 className="text-sm font-medium text-zinc-300">Datasets</h3>
        {datasets.length === 0 ? (
          <p className="mt-2 text-sm text-zinc-500">No imported datasets yet.</p>
        ) : (
          <ul className="mt-2 space-y-2 text-sm text-zinc-400">
            {datasets.map((d) => (
              <li key={d.id}>
                {d.timeframe} · {d.row_count} rows · {d.validation_status}
              </li>
            ))}
          </ul>
        )}
      </section>
    </div>
  );
}