"use client";

import { useEffect, useState } from "react";
import { LeaderboardCard, type LeaderboardEntry } from "@/components/LeaderboardCard";
import { apiFetch } from "@/lib/api";

export default function ResultsPage() {
  const [rows, setRows] = useState<LeaderboardEntry[]>([]);
  const [showAll, setShowAll] = useState(false);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    setLoading(true);
    apiFetch<LeaderboardEntry[]>(`/api/v1/autopilot/leaderboard?profitable_only=${!showAll}&limit=40`)
      .then(setRows)
      .finally(() => setLoading(false));
  }, [showAll]);

  return (
    <div className="space-y-6">
      <header className="flex flex-col gap-3 md:flex-row md:items-end md:justify-between">
        <div>
          <h2 className="page-title">Prop results</h2>
          <p className="page-sub">
            Each card shows when it was tested, the sample window, and the stop/$ risk it took. Default:
            keepers. Green P&amp;L with too few trades is a sample-size miss, not a losing strategy.
          </p>
        </div>
        <label className="flex items-center gap-2 text-sm text-zinc-400">
          <input
            type="checkbox"
            checked={showAll}
            onChange={(e) => setShowAll(e.target.checked)}
            className="rounded border-zinc-600"
          />
          Include gate misses
        </label>
      </header>

      {loading ? (
        <p className="text-zinc-500">Loading…</p>
      ) : rows.length === 0 ? (
        <p className="text-sm text-zinc-500">No runs match this filter. Run a prop search from Home.</p>
      ) : (
        <ul className="space-y-4">
          {rows.map((r) => (
            <LeaderboardCard key={r.run_id} row={r} />
          ))}
        </ul>
      )}
    </div>
  );
}