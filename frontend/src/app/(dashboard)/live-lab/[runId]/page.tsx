"use client";

import { useParams } from "next/navigation";
import { useCallback, useEffect, useState } from "react";

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

export default function LiveStrategyRunPage() {
  const { runId } = useParams<{ runId: string }>();
  const [detail, setDetail] = useState<RunDetail | null>(null);

  const load = useCallback(async () => {
    if (!runId) return;
    setDetail(await apiFetch<RunDetail>(`/api/v1/live-lab/forward-tests/${runId}`));
  }, [runId]);

  useEffect(() => {
    load();
  }, [load]);

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
      </header>

      <div className="grid grid-cols-2 gap-3">
        <div className="rounded-lg border border-zinc-800 p-3">
          <p className="text-xs text-zinc-500">Net P&amp;L</p>
          <p className="text-lg font-semibold text-white">${r.net_pnl.toFixed(2)}</p>
        </div>
        <div className="rounded-lg border border-zinc-800 p-3">
          <p className="text-xs text-zinc-500">Trades</p>
          <p className="text-lg font-semibold text-white">{r.trade_count}</p>
        </div>
      </div>

      <div className="flex gap-2">
        <Button variant="secondary" onClick={pause}>
          Pause
        </Button>
        <Button onClick={resume}>Resume</Button>
      </div>

      {!detail.validation.passed && (
        <p className="rounded border border-amber-500/30 bg-amber-950/20 p-2 text-xs text-amber-100">
          Historical validation: {detail.validation.reasons.join(", ") || "not passed"}
        </p>
      )}

      <section>
        <h2 className="mb-2 text-sm font-semibold text-zinc-200">Decision &amp; fill ledger</h2>
        <ul className="max-h-[50vh] space-y-2 overflow-y-auto text-xs">
          {detail.ledger.map((e) => (
            <li key={e.sequence} className="rounded border border-zinc-800 bg-zinc-950/40 p-2">
              <p className="font-medium text-cyan-300/90">{e.event_type}</p>
              <p className="text-zinc-500">
                {e.exchange_ts ? `ex ${new Date(e.exchange_ts).toLocaleString()}` : ""}
                {e.decision_ts ? ` · decision ${new Date(e.decision_ts).toLocaleString()}` : ""}
              </p>
              <pre className="mt-1 overflow-x-auto text-[10px] text-zinc-400">{JSON.stringify(e.payload, null, 0)}</pre>
            </li>
          ))}
        </ul>
      </section>

      <p className="text-[11px] text-zinc-600">
        Chart overlays and equity curve require additional bars API wiring. Ledger is authoritative for audit.
      </p>
    </div>
  );
}