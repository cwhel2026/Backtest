"use client";

import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { apiFetch } from "@/lib/api";

type StrategyDetail = {
  id: string;
  name: string;
  symbol: string;
  category: string;
  timeframe: string;
  lifecycle: string;
  current_version: { specification: Record<string, unknown>; version_number: number } | null;
  latest_backtest: { id: string; reproducibility_id: string; metrics: Record<string, number | null> } | null;
};

export default function StrategyDetailPage() {
  const { id } = useParams<{ id: string }>();
  const router = useRouter();
  const [detail, setDetail] = useState<StrategyDetail | null>(null);
  const [cloning, setCloning] = useState(false);

  async function cloneStrategy() {
    if (!id) return;
    setCloning(true);
    try {
      const copy = await apiFetch<StrategyDetail>(`/api/v1/strategies/${id}/clone`, {
        method: "POST",
        body: JSON.stringify({}),
      });
      router.push(`/strategies/${copy.id}`);
    } finally {
      setCloning(false);
    }
  }

  useEffect(() => {
    if (!id) return;
    apiFetch<StrategyDetail>(`/api/v1/strategies/${id}`).then(setDetail);
  }, [id]);

  if (!detail) return <p className="text-zinc-500">Loading strategy…</p>;

  return (
    <div className="space-y-6 max-w-4xl">
      <header className="flex flex-col gap-3 md:flex-row md:items-start md:justify-between">
        <div>
          <h2 className="page-title">{detail.name}</h2>
          <p className="page-sub">
            {detail.symbol} · {detail.category} · {detail.timeframe} · {detail.lifecycle}
          </p>
        </div>
        <button
          type="button"
          disabled={cloning}
          onClick={cloneStrategy}
          className="rounded-md border border-zinc-700 px-3 py-2 text-sm text-zinc-200 hover:bg-zinc-900 disabled:opacity-50"
        >
          {cloning ? "Cloning…" : "Clone"}
        </button>
      </header>

      {detail.latest_backtest ? (
        <section className="rounded-lg border border-zinc-800 bg-[#181b22] p-4 text-sm">
          <p className="font-medium text-zinc-200">Latest backtest (historical simulation only)</p>
          <p className="mt-2 text-zinc-400">
            Repro ID: <span className="font-mono text-xs">{detail.latest_backtest.reproducibility_id}</span>
          </p>
          <Link href={`/backtests/${detail.latest_backtest.id}`} className="mt-2 inline-block text-emerald-400">
            View run →
          </Link>
        </section>
      ) : (
        <p className="text-sm text-zinc-500">No completed backtests yet.</p>
      )}

      {detail.current_version ? (
        <section>
          <h3 className="text-sm font-medium text-zinc-300">Executable specification v{detail.current_version.version_number}</h3>
          <pre className="mt-2 overflow-auto rounded-lg border border-zinc-800 bg-black/40 p-4 text-xs text-zinc-300">
            {JSON.stringify(detail.current_version.specification, null, 2)}
          </pre>
        </section>
      ) : null}
    </div>
  );
}