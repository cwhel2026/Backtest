"use client";

import Link from "next/link";
import { useCallback, useEffect, useState } from "react";

import { Button } from "@/components/ui/Button";
import { apiFetch } from "@/lib/api";

type CertDash = {
  latest: {
    status: string;
    symbol: string;
    replay_fingerprint: string | null;
    detail: string | null;
    payload: Record<string, unknown>;
    created_at: string;
  } | null;
  history: { id: string; status: string; symbol: string; created_at: string }[];
  disclaimer: string;
  strategy_readiness?: Record<string, Record<string, unknown>>;
};

const STATUS_COLOR: Record<string, string> = {
  CERTIFIED_FOR_PAPER_RESEARCH: "text-emerald-400",
  EXPERIMENTAL: "text-amber-300",
  FAILED_CERTIFICATION: "text-red-400",
  NOT_TESTED: "text-zinc-400",
};

export default function AccuracyCertificationPage() {
  const [data, setData] = useState<CertDash | null>(null);
  const [busy, setBusy] = useState(false);

  const load = useCallback(async () => {
    setData(await apiFetch<CertDash>("/api/v1/live-lab/certification/dashboard"));
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  async function runCert() {
    setBusy(true);
    try {
      await apiFetch("/api/v1/live-lab/certification/run?symbol=MES", { method: "POST" });
      await load();
    } finally {
      setBusy(false);
    }
  }

  const latest = data?.latest;
  const statusClass = STATUS_COLOR[latest?.status ?? "NOT_TESTED"] ?? "text-zinc-300";

  return (
    <div className="space-y-5 pb-24">
      <header>
        <Link href="/paper-trading" className="text-xs text-cyan-400">
          ← Paper Trading
        </Link>
        <h1 className="page-title mt-2 text-xl font-semibold text-white">Accuracy Certification</h1>
        <p className="text-sm text-zinc-400">Replay, restart recovery, and backtest/forward parity checks.</p>
      </header>

      <section className="rounded-xl border border-zinc-800 bg-zinc-900/60 p-4">
        <p className="text-xs uppercase text-zinc-500">Status</p>
        <p className={`text-lg font-semibold ${statusClass}`}>{latest?.status ?? "NOT TESTED"}</p>
        {latest?.detail && <p className="mt-1 text-sm text-zinc-400">{latest.detail}</p>}
        {latest?.replay_fingerprint && (
          <p className="mt-2 break-all font-mono text-[10px] text-zinc-500">fp {latest.replay_fingerprint}</p>
        )}
        <Button className="mt-3" disabled={busy} onClick={runCert}>
          Run certification (MES)
        </Button>
      </section>

      {data?.strategy_readiness && (
        <section className="rounded-xl border border-zinc-800 p-3 text-xs">
          <h2 className="text-sm font-semibold text-zinc-200">Strategy readiness</h2>
          <pre className="mt-2 overflow-auto text-[10px] text-zinc-400">
            {JSON.stringify(data.strategy_readiness, null, 2)}
          </pre>
        </section>
      )}

      {latest?.payload && (
        <section className="rounded-xl border border-zinc-800 p-3">
          <h2 className="text-sm font-semibold text-zinc-200">Technical evidence</h2>
          <pre className="mt-2 max-h-64 overflow-auto text-[10px] text-zinc-400">
            {JSON.stringify(latest.payload, null, 2)}
          </pre>
        </section>
      )}

      <section>
        <h2 className="mb-2 text-sm font-semibold text-zinc-200">History</h2>
        <ul className="space-y-2 text-xs">
          {(data?.history ?? []).map((h) => (
            <li key={h.id} className="flex justify-between rounded border border-zinc-800 px-2 py-1">
              <span>{h.symbol}</span>
              <span className={STATUS_COLOR[h.status] ?? ""}>{h.status}</span>
            </li>
          ))}
        </ul>
      </section>

      <p className="text-[11px] text-zinc-600">{data?.disclaimer}</p>
    </div>
  );
}