"use client";

import Link from "next/link";
import { FormEvent, useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { apiFetch } from "@/lib/api";

type Instrument = { id: string; symbol: string };

const TEMPLATES: Record<
  string,
  { category: string; entry: Record<string, unknown>; exit: Record<string, unknown> }
> = {
  orb: {
    category: "opening_range_breakout",
    entry: { type: "opening_range_breakout", range_minutes: 15, side: "both" },
    exit: { stop_ticks: 20, target_ticks: 40, session_end_flatten: true },
  },
  ema: {
    category: "trend_continuation",
    entry: { type: "ema_crossover", fast_period: 8, slow_period: 21 },
    exit: { stop_ticks: 16, target_ticks: 24, session_end_flatten: true },
  },
  vwap: {
    category: "vwap_mean_reversion",
    entry: { type: "vwap_reversion", deviation_ticks: 16 },
    exit: { stop_ticks: 24, target_ticks: 32, session_end_flatten: true },
  },
};

export default function NewStrategyPage() {
  const router = useRouter();
  const [instruments, setInstruments] = useState<Instrument[]>([]);
  const [symbol, setSymbol] = useState("MES");
  const [timeframe, setTimeframe] = useState("5m");
  const [template, setTemplate] = useState("orb");
  const [name, setName] = useState("");
  const [rationale, setRationale] = useState("");
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    apiFetch<Instrument[]>("/api/v1/instruments").then(setInstruments);
  }, []);

  async function onSubmit(e: FormEvent) {
    e.preventDefault();
    setError(null);
    const t = TEMPLATES[template];
    const spec = {
      name: name || `${symbol} ${timeframe} ${template}`,
      instrument_symbol: symbol,
      timeframe,
      category: t.category,
      session: { allowed: ["RTH"], timezone: "America/Chicago" },
      entry: t.entry,
      exit: t.exit,
      risk: { dollar_risk_per_trade: 75, max_contracts: 3 },
    };
    try {
      const created = await apiFetch<{ id: string }>("/api/v1/strategies", {
        method: "POST",
        body: JSON.stringify({
          specification: spec,
          economic_rationale: rationale || spec.name,
        }),
      });
      router.push(`/strategies/${created.id}`);
    } catch (err) {
      setError(String(err));
    }
  }

  return (
    <div className="mx-auto max-w-xl space-y-6">
      <header>
        <h2 className="page-title">New strategy</h2>
        <p className="page-sub">Declarative DSL — no arbitrary code.</p>
      </header>
      <form onSubmit={onSubmit} className="space-y-4 rounded-lg border border-zinc-800 bg-[#181b22] p-4 md:p-6">
        <label className="flex flex-col gap-1 text-sm text-zinc-400">
          Name
          <input
            className="rounded-md border border-zinc-700 bg-zinc-900 px-3 py-2"
            value={name}
            onChange={(e) => setName(e.target.value)}
            placeholder="MES 5m ORB"
          />
        </label>
        <label className="flex flex-col gap-1 text-sm text-zinc-400">
          Template
          <select
            className="rounded-md border border-zinc-700 bg-zinc-900 px-3 py-2"
            value={template}
            onChange={(e) => setTemplate(e.target.value)}
          >
            <option value="orb">Opening range breakout</option>
            <option value="ema">EMA crossover</option>
            <option value="vwap">VWAP reversion</option>
          </select>
        </label>
        <div className="flex flex-col gap-3 md:flex-row">
          <label className="flex flex-1 flex-col gap-1 text-sm text-zinc-400">
            Symbol
            <select
              className="rounded-md border border-zinc-700 bg-zinc-900 px-3 py-2"
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
          <label className="flex flex-1 flex-col gap-1 text-sm text-zinc-400">
            Timeframe
            <select
              className="rounded-md border border-zinc-700 bg-zinc-900 px-3 py-2"
              value={timeframe}
              onChange={(e) => setTimeframe(e.target.value)}
            >
              <option value="5m">5m</option>
              <option value="1m">1m</option>
              <option value="15m">15m</option>
              <option value="1h">1h</option>
            </select>
          </label>
        </div>
        <label className="flex flex-col gap-1 text-sm text-zinc-400">
          Hypothesis
          <textarea
            className="min-h-[72px] rounded-md border border-zinc-700 bg-zinc-900 px-3 py-2 text-sm"
            value={rationale}
            onChange={(e) => setRationale(e.target.value)}
          />
        </label>
        {error ? <p className="text-sm text-red-400">{error}</p> : null}
        <div className="flex flex-col gap-2 md:flex-row">
          <button type="submit" className="rounded-md bg-emerald-700 px-4 py-2 text-sm text-white hover:bg-emerald-600">
            Create strategy
          </button>
          <Link href="/strategies" className="rounded-md border border-zinc-700 px-4 py-2 text-center text-sm text-zinc-300">
            Cancel
          </Link>
        </div>
      </form>
    </div>
  );
}