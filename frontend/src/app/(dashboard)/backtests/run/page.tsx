"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useMemo, useState } from "react";
import { BacktestStepper } from "@/components/backtest/BacktestStepper";
import { Button } from "@/components/ui/Button";
import { Card } from "@/components/ui/Card";
import { apiFetch } from "@/lib/api";
import { FEATURED_STRATEGIES } from "@/lib/strategy-catalog";

type Strategy = { id: string; name: string; symbol: string | null; timeframe: string; category: string };
type Instrument = { id: string; symbol: string; name: string };
type Dataset = {
  id: string;
  instrument_id: string;
  timeframe: string;
  genuine_for_research?: boolean | null;
  meta?: { label?: string; data_lineage?: string };
};

export default function BacktestWizardPage() {
  const router = useRouter();
  const [step, setStep] = useState(0);
  const [strategies, setStrategies] = useState<Strategy[]>([]);
  const [instruments, setInstruments] = useState<Instrument[]>([]);
  const [datasets, setDatasets] = useState<Dataset[]>([]);
  const [strategyId, setStrategyId] = useState("");
  const [instrumentId, setInstrumentId] = useState("");
  const [datasetId, setDatasetId] = useState("");
  const [slippage, setSlippage] = useState(1);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    Promise.all([
      apiFetch<Strategy[]>("/api/v1/strategies"),
      apiFetch<Instrument[]>("/api/v1/instruments"),
      apiFetch<Dataset[]>("/api/v1/market-data/datasets"),
    ]).then(([s, i, d]) => {
      setStrategies(s);
      setInstruments(i);
      setDatasets(d);
    });
  }, []);

  const instrument = instruments.find((x) => x.id === instrumentId);
  const filteredDatasets = useMemo(() => {
    if (!instrumentId) return datasets;
    return datasets.filter((d) => d.instrument_id === instrumentId);
  }, [datasets, instrumentId]);

  const selectedStrategy = strategies.find((s) => s.id === strategyId);

  async function runBacktest() {
    if (!strategyId || !datasetId) return;
    setSubmitting(true);
    setError(null);
    try {
      const run = await apiFetch<{ id: string }>("/api/v1/backtests", {
        method: "POST",
        body: JSON.stringify({
          strategy_id: strategyId,
          dataset_id: datasetId,
          assumptions: { slippage_ticks_per_side: slippage },
          parameters: {},
        }),
      });
      router.push(`/backtests/${run.id}`);
    } catch (e) {
      setError(String(e));
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <div className="space-y-6">
      <header>
        <h1 className="page-title">New backtest</h1>
        <p className="page-sub">Five short steps — defaults favor genuine datasets when available.</p>
      </header>

      <BacktestStepper step={step} />

      {step === 0 ? (
        <section className="space-y-3">
          <h2 className="text-sm font-medium text-zinc-300">Choose strategy</h2>
          <ul className="space-y-2">
            {FEATURED_STRATEGIES.map((f) => (
              <li key={f.key}>
                <Card>
                  <p className="font-semibold text-zinc-100">{f.name}</p>
                  <p className="mt-1 text-sm text-zinc-400">{f.summary}</p>
                  <Link href={f.href} className="mt-2 inline-block text-sm text-[var(--accent)]">
                    Open template →
                  </Link>
                </Card>
              </li>
            ))}
          </ul>
          <div className="space-y-2">
            {strategies.map((s) => (
              <button
                key={s.id}
                type="button"
                onClick={() => setStrategyId(s.id)}
                className={`w-full rounded-2xl border px-4 py-3 text-left text-sm ${
                  strategyId === s.id ? "border-[var(--accent)] bg-[var(--accent-muted)]" : "border-[var(--border)]"
                }`}
              >
                <span className="font-medium text-zinc-100">{s.name}</span>
                <span className="mt-0.5 block text-xs text-zinc-500">
                  {s.symbol ?? "—"} · {s.timeframe} · {s.category}
                </span>
              </button>
            ))}
          </div>
          <Button fullWidth disabled={!strategyId} onClick={() => setStep(1)}>
            Next: market
          </Button>
        </section>
      ) : null}

      {step === 1 ? (
        <section className="space-y-3">
          <h2 className="text-sm font-medium text-zinc-300">Choose market</h2>
          <InstrumentGrid instruments={instruments} instrumentId={instrumentId} setInstrumentId={setInstrumentId} />
          <div className="flex gap-2">
            <Button variant="secondary" className="flex-1" onClick={() => setStep(0)}>
              Back
            </Button>
            <Button className="flex-1" disabled={!instrumentId} onClick={() => setStep(2)}>
              Next: dataset
            </Button>
          </div>
        </section>
      ) : null}

      {step === 2 ? (
        <section className="space-y-3">
          <h2 className="text-sm font-medium text-zinc-300">
            Dataset for {instrument?.symbol ?? "instrument"}
          </h2>
          {filteredDatasets.length === 0 ? (
            <Card>
              <p className="text-sm text-zinc-400">No datasets for this market. Import history on Market Data first.</p>
              <Link href="/market-data" className="mt-3 inline-block text-sm text-[var(--accent)]">
                Market Data →
              </Link>
            </Card>
          ) : (
            filteredDatasets.map((d) => (
              <button
                key={d.id}
                type="button"
                onClick={() => setDatasetId(d.id)}
                className={`w-full rounded-2xl border px-4 py-3 text-left text-sm ${
                  datasetId === d.id ? "border-[var(--accent)] bg-[var(--accent-muted)]" : "border-[var(--border)]"
                }`}
              >
                <span className="font-medium">{d.timeframe}</span>
                <span className="ml-2 text-xs text-zinc-500">
                  {d.genuine_for_research ? "Genuine" : "Not genuine — backtest may be blocked"}
                </span>
              </button>
            ))
          )}
          <div className="flex gap-2">
            <Button variant="secondary" className="flex-1" onClick={() => setStep(1)}>
              Back
            </Button>
            <Button className="flex-1" disabled={!datasetId} onClick={() => setStep(3)}>
              Next: risk
            </Button>
          </div>
        </section>
      ) : null}

      {step === 3 ? (
        <section className="space-y-4">
          <h2 className="text-sm font-medium text-zinc-300">Execution assumptions</h2>
          <label className="block text-sm text-zinc-400">
            Slippage (ticks per side)
            <input
              type="number"
              min={0}
              max={10}
              value={slippage}
              onChange={(e) => setSlippage(Number(e.target.value))}
              className="mt-2 w-full rounded-xl border border-[var(--border)] bg-[var(--card-elevated)] px-4 py-3 text-zinc-100"
            />
          </label>
          <p className="text-xs text-zinc-500">
            Strategy-specific stops and targets stay in the strategy definition — only friction is set here.
          </p>
          <div className="flex gap-2">
            <Button variant="secondary" className="flex-1" onClick={() => setStep(2)}>
              Back
            </Button>
            <Button className="flex-1" onClick={() => setStep(4)}>
              Review
            </Button>
          </div>
        </section>
      ) : null}

      {step === 4 ? (
        <section className="space-y-4">
          <Card className="space-y-2 text-sm">
            <p>
              <span className="text-zinc-500">Strategy:</span> {selectedStrategy?.name ?? strategyId.slice(0, 8)}
            </p>
            <p>
              <span className="text-zinc-500">Market:</span> {instrument?.symbol}
            </p>
            <p>
              <span className="text-zinc-500">Dataset:</span> {datasetId.slice(0, 8)}…
            </p>
            <p>
              <span className="text-zinc-500">Slippage:</span> {slippage} tick/side
            </p>
          </Card>
          {error ? <p className="text-sm text-red-300">{error}</p> : null}
          <RunActions submitting={submitting} setStep={setStep} runBacktest={runBacktest} />
        </section>
      ) : null}
    </div>
  );
}

function InstrumentGrid({
  instruments,
  instrumentId,
  setInstrumentId,
}: {
  instruments: Instrument[];
  instrumentId: string;
  setInstrumentId: (id: string) => void;
}) {
  return (
    <div className="grid grid-cols-2 gap-2 sm:grid-cols-3">
      {instruments.map((i) => (
        <button
          key={i.id}
          type="button"
          onClick={() => setInstrumentId(i.id)}
          className={`min-h-[64px] rounded-2xl border px-3 py-3 text-sm font-semibold ${
            instrumentId === i.id ? "border-[var(--accent)] bg-[var(--accent-muted)]" : "border-[var(--border)]"
          }`}
        >
          {i.symbol}
        </button>
      ))}
    </div>
  );
}

function RunActions({
  submitting,
  setStep,
  runBacktest,
}: {
  submitting: boolean;
  setStep: (n: number) => void;
  runBacktest: () => void;
}) {
  return (
    <div className="flex gap-2">
      <Button variant="secondary" className="flex-1" onClick={() => setStep(3)}>
        Back
      </Button>
      <Button className="flex-1" disabled={submitting} onClick={runBacktest}>
        {submitting ? "Queuing…" : "Run backtest"}
      </Button>
    </div>
  );
}