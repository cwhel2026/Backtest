"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { ApiHttpError, apiFetch } from "@/lib/api";
import { Button } from "@/components/ui/Button";
import { Card } from "@/components/ui/Card";

type SetupInfo = {
  symbols: string[];
  databento_symbols: string[];
  default_start: string;
  default_end: string;
  default_history_days: number;
  dataset: string;
  schema: string;
  configured: boolean;
  storage_total_hint_gb: string;
  continuous_series: string;
};

type BundleEstimate = {
  estimated_usd_total?: number;
  estimated_gbp_total?: number;
  symbols?: Record<string, { estimated_usd?: number; databento_symbol?: string }>;
  note?: string;
};

const STEPS = ["Provider", "Markets", "Range", "Price", "Import"] as const;

export default function DatabentoSetupPage() {
  const [step, setStep] = useState(0);
  const [setup, setSetup] = useState<SetupInfo | null>(null);
  const [estimate, setEstimate] = useState<BundleEstimate | null>(null);
  const [approve, setApprove] = useState(false);
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState<string | null>(null);

  useEffect(() => {
    apiFetch<SetupInfo>("/api/v1/market-data/databento/setup").then(setSetup).catch(() => undefined);
  }, []);

  async function runEstimate() {
    if (!setup) return;
    setBusy(true);
    setResult(null);
    try {
      const est = await apiFetch<BundleEstimate>("/api/v1/market-data/ingest/estimate-bundle", {
        method: "POST",
        body: JSON.stringify({
          provider_slug: "databento",
          symbols: setup.symbols,
          start: setup.default_start,
          end: setup.default_end,
        }),
      });
      setEstimate(est);
      setStep(3);
    } catch (e) {
      setResult(String(e));
    } finally {
      setBusy(false);
    }
  }

  async function startImport() {
    if (!setup || !approve) return;
    setBusy(true);
    setResult(null);
    try {
      const res = await apiFetch<{ message?: string; job_ids?: string[] }>("/api/v1/market-data/ingest/bundle", {
        method: "POST",
        body: JSON.stringify({
          provider_slug: "databento",
          symbols: setup.symbols,
          start: setup.default_start,
          end: setup.default_end,
          confirm_paid: true,
          approved_cost_usd: estimate?.estimated_usd_total,
          derive_timeframes: true,
        }),
      });
      setResult(res.message || `Queued ${res.job_ids?.length ?? 0} jobs`);
      setStep(4);
    } catch (e) {
      if (e instanceof ApiHttpError && e.status === 402) {
        const det = e.detail as { message?: string; estimate?: BundleEstimate };
        setEstimate(det.estimate || estimate);
        setResult(det.message || "Approve paid download after reviewing the estimate.");
        setStep(3);
      } else {
        setResult(String(e));
      }
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="space-y-6">
      <header>
        <h1 className="page-title">Licensed history setup</h1>
        <p className="page-sub">
          Databento GLBX.MDP3 · five years · MNQ, MES, MGC. Your API key stays on the server.
        </p>
      </header>

      <ol className="flex gap-1">
        {STEPS.map((label, i) => (
          <li key={label} className="flex-1">
            <div className={`h-1.5 rounded-full ${i <= step ? "bg-[var(--accent)]" : "bg-zinc-800"}`} />
            <p className={`mt-1 text-[10px] ${i === step ? "text-[var(--accent)]" : "text-zinc-600"}`}>{label}</p>
          </li>
        ))}
      </ol>

      {step === 0 && (
        <Card className="space-y-3 text-sm text-zinc-300">
          <p>
            <strong className="text-zinc-100">Databento</strong> is the licensed CME Globex feed. We download{" "}
            <strong className="text-zinc-100">1-minute OHLCV</strong>, validate, then build 5m / 15m / 1h / 4h for backtests.
          </p>
          <p className="text-zinc-500">
            Status: {setup?.configured ? "API key configured on server" : "Set DATABENTO_API_KEY on Railway first"}
          </p>
          <Button fullWidth onClick={() => setStep(1)} disabled={!setup}>
            Continue
          </Button>
        </Card>
      )}

      {step === 1 && setup && (
        <section className="space-y-3">
          <h2 className="text-sm font-medium text-zinc-200">Markets (pre-selected)</h2>
          <ul className="grid gap-2">
            {setup.symbols.map((s, i) => (
              <Card key={s} className="py-3">
                <p className="font-semibold text-zinc-100">{s}</p>
                <p className="text-xs text-zinc-500">{setup.databento_symbols[i]} · continuous unadjusted</p>
              </Card>
            ))}
          </ul>
          <div className="flex gap-2">
            <Button variant="secondary" className="flex-1" onClick={() => setStep(0)}>
              Back
            </Button>
            <Button className="flex-1" onClick={() => setStep(2)}>
              Next
            </Button>
          </div>
        </section>
      )}

      {step === 2 && setup && (
        <section className="space-y-3">
          <h2 className="text-sm font-medium text-zinc-200">Date range</h2>
          <Card className="text-sm text-zinc-300">
            <p>About {setup.default_history_days} days of history (to the latest available bar).</p>
            <p className="mt-2 font-mono text-xs text-zinc-500">
              {setup.default_start.slice(0, 10)} → {setup.default_end.slice(0, 10)}
            </p>
            <p className="mt-2 text-xs text-zinc-500">Storage hint: {setup.storage_total_hint_gb}</p>
          </Card>
          <div className="flex gap-2">
            <Button variant="secondary" className="flex-1" onClick={() => setStep(1)}>
              Back
            </Button>
            <Button className="flex-1" disabled={busy} onClick={runEstimate}>
              {busy ? "Checking price…" : "Get Databento estimate"}
            </Button>
          </div>
        </section>
      )}

      {step >= 3 && estimate && (
        <section className="space-y-3">
          <h2 className="text-sm font-medium text-zinc-200">Official estimate (not a purchase)</h2>
          <Card className="space-y-2 text-sm">
            <p className="text-2xl font-semibold tabular-nums text-zinc-50">
              ${estimate.estimated_usd_total?.toFixed(2) ?? "—"}
              {estimate.estimated_gbp_total != null ? (
                <span className="ml-2 text-base text-zinc-400">≈ £{estimate.estimated_gbp_total.toFixed(2)}</span>
              ) : null}
            </p>
            <p className="text-xs text-zinc-500">{estimate.note}</p>
            <ul className="text-xs text-zinc-400">
              {setup?.symbols.map((s) => (
                <li key={s}>
                  {s}: ${estimate.symbols?.[s]?.estimated_usd?.toFixed(2) ?? "—"} ({estimate.symbols?.[s]?.databento_symbol})
                </li>
              ))}
            </ul>
          </Card>
          <label className="flex min-h-[44px] items-center gap-3 text-sm text-zinc-300">
            <input
              type="checkbox"
              checked={approve}
              onChange={(e) => setApprove(e.target.checked)}
              className="h-5 w-5 rounded border-zinc-600"
            />
            I approve this estimated charge and want to start the download
          </label>
          <Button fullWidth disabled={!approve || busy || !setup?.configured} onClick={startImport}>
            {busy ? "Queueing…" : "Start import"}
          </Button>
          {!setup?.configured ? (
            <p className="text-xs text-amber-300">Configure DATABENTO_API_KEY on Railway before importing.</p>
          ) : null}
        </section>
      )}

      {step === 4 && (
        <Card className="text-sm text-zinc-300">
          <p>{result}</p>
          <p className="mt-2">
            Track progress under{" "}
            <Link href="/research" className="text-[var(--accent)]">
              AI Research
            </Link>{" "}
            and datasets on{" "}
            <Link href="/market-data" className="text-[var(--accent)]">
              Market Data
            </Link>
            .
          </p>
        </Card>
      )}

      {result && step < 4 ? <p className="text-sm text-red-300">{result}</p> : null}

      <Link href="/market-data" className="text-sm text-[var(--accent)]">
        ← Advanced library &amp; charts
      </Link>
    </div>
  );
}