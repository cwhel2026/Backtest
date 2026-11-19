"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { LeaderboardCard, type LeaderboardEntry } from "@/components/LeaderboardCard";
import { Card } from "@/components/ui/Card";
import { EmptyState } from "@/components/ui/EmptyState";
import { apiFetch } from "@/lib/api";

export default function AnalyticsPage() {
  const [board, setBoard] = useState<LeaderboardEntry[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    apiFetch<LeaderboardEntry[]>("/api/v1/autopilot/leaderboard?profitable_only=false&limit=25")
      .then(setBoard)
      .catch(() => setBoard([]))
      .finally(() => setLoading(false));
  }, []);

  return (
    <div className="space-y-6 pb-8">
      <header>
        <h1 className="page-title">Analytics</h1>
        <p className="page-sub">Ranked research results from persisted backtests and validated strategies — not estimates.</p>
      </header>

      <div className="flex flex-wrap gap-2">
        <Link href="/strategy-compare">
          <Card className="panel px-4 py-3 text-sm font-medium text-[var(--accent)]">Compare strategies →</Card>
        </Link>
        <Link href="/leaderboard">
          <Card className="panel px-4 py-3 text-sm text-zinc-400">Legacy leaderboard view</Card>
        </Link>
      </div>

      <section className="space-y-4">
        <h2 className="text-sm font-semibold text-zinc-200">Research leaderboard</h2>
        {loading ? (
          <p className="text-sm text-zinc-500">Loading…</p>
        ) : board.length === 0 ? (
          <EmptyState
            title="No ranked results"
            description="Complete backtests on genuine datasets or finish prop-desk search runs to populate analytics."
            actionHref="/backtests/run"
            actionLabel="Run a backtest"
          />
        ) : (
          <ul className="space-y-3">
            {board.map((row) => (
              <LeaderboardCard key={row.run_id} row={row} />
            ))}
          </ul>
        )}
      </section>
    </div>
  );
}