"use client";

import { useState } from "react";
import { apiFetch } from "@/lib/api";

type Row = {
  run_id: string;
  entry_type: string | null;
  trade_count: number | null;
  win_rate: number | null;
  profit_factor: number | null;
  total_net_profit: number | null;
  max_drawdown: number | null;
  expectancy_per_trade: number | null;
};

export default function StrategyComparePage() {
  const [runIds, setRunIds] = useState("");
  const [rows, setRows] = useState<Row[]>([]);
  const [note, setNote] = useState("");

  async function load() {
    const q = runIds
      .split(",")
      .map((s) => s.trim())
      .filter(Boolean)
      .join(",");
  if (!q) return;
    const res = await apiFetch<{ runs: Row[]; note: string }>(
      `/api/v1/berg-tnb/compare?run_ids=${encodeURIComponent(q)}`,
    );
    setRows(res.runs);
    setNote(res.note);
  }

  return (
    <div className="mx-auto max-w-5xl space-y-6 p-6 text-zinc-200">
      <h1 className="text-xl font-semibold">Strategy comparison</h1>
      <p className="text-sm text-zinc-400">
        Compare Video Liquidity Sweep, Video Anchor BOS, and Berg TNB on the same dataset and cost assumptions.
      </p>
      <CompareInput runIds={runIds} setRunIds={setRunIds} onLoad={() => { void load(); }} />
      {note && <p className="text-xs text-zinc-500">{note}</p>}
      {rows.length > 0 && (
        <table className="w-full text-left text-sm">
          <thead className="text-zinc-500">
            <tr>
              <th className="py-2">Strategy</th>
              <th>Trades</th>
              <th>Win %</th>
              <th>PF</th>
              <th>Net P&L</th>
              <th>Max DD</th>
              <th>Expectancy</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((r) => (
              <tr key={r.run_id} className="border-t border-zinc-800">
                <td className="py-2 font-mono text-xs">{r.entry_type ?? r.run_id}</td>
                <td>{r.trade_count ?? "—"}</td>
                <td>{r.win_rate != null ? (r.win_rate * 100).toFixed(1) : "—"}</td>
                <td>{r.profit_factor?.toFixed(2) ?? "—"}</td>
                <td>{r.total_net_profit?.toFixed(2) ?? "—"}</td>
                <td>{r.max_drawdown?.toFixed(2) ?? "—"}</td>
                <td>{r.expectancy_per_trade?.toFixed(2) ?? "—"}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  );
}

function CompareInput({
  runIds,
  setRunIds,
  onLoad,
}: {
  runIds: string;
  setRunIds: (v: string) => void;
  onLoad: () => void;
}) {
  return (
    <div className="flex flex-wrap gap-2">
      <input
        className="min-w-[320px] flex-1 rounded border border-zinc-700 bg-zinc-900 px-3 py-2 text-sm"
        placeholder="Backtest run UUIDs (comma-separated)"
        value={runIds}
        onChange={(e) => setRunIds(e.target.value)}
      />
      <button
        type="button"
        onClick={onLoad}
        className="rounded bg-zinc-700 px-4 py-2 text-sm hover:bg-zinc-600"
      >
        Compare
      </button>
    </div>
  );
}