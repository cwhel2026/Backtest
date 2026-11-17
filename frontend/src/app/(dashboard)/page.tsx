"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { LeaderboardCard, type LeaderboardEntry } from "@/components/LeaderboardCard";
import { apiFetch } from "@/lib/api";

type AutopilotStatus = {
  hourly_enabled: boolean;
  ai_configured: boolean;
  message: string;
  profitable_candidates: LeaderboardEntry[];
  recent_activity: { headline: string; detail: string; created_at: string }[];
  cycle_stats: { tests_run: number; profitable_count: number; last_cycle_detail: string | null };
  search_symbols: string[];
};

export default function HomePage() {
  const [status, setStatus] = useState<AutopilotStatus | null>(null);
  const [running, setRunning] = useState(false);
  const [note, setNote] = useState<string | null>(null);

  function refresh() {
    apiFetch<AutopilotStatus>("/api/v1/autopilot/status").then(setStatus).catch((e) => setNote(String(e)));
  }

  useEffect(() => {
    refresh();
    const t = setInterval(refresh, 15000);
    return () => clearInterval(t);
  }, []);

  async function runNow() {
    setRunning(true);
    setNote(null);
    try {
      const res = await apiFetch<{ status: string; mode: string }>("/api/v1/autopilot/run", { method: "POST" });
      setNote(
        res.mode === "inline"
          ? "Deep search running (100s of combos per symbol) — allow 5–8 minutes, then refresh."
          : "Deep search queued — allow several minutes, then refresh."
      );
      setTimeout(refresh, 5000);
    } catch (e) {
      setNote(String(e));
    } finally {
      setRunning(false);
    }
  }

  const candidates = status?.profitable_candidates ?? [];

  return (
    <div className="space-y-8">
      <header>
        <h2 className="page-title">Prop firm autopilot</h2>
        <p className="page-sub">Only profitable, named strategies appear below — losers are filtered out.</p>
      </header>

      <section className="rounded-xl border border-emerald-900/50 bg-gradient-to-r from-emerald-950/40 to-[#181b22] p-4 md:p-6">
        <p className="text-sm leading-relaxed text-zinc-200">{status?.message}</p>
        <div className="mt-3 flex flex-wrap gap-2 text-xs text-zinc-400">
          <span className="rounded-full border border-violet-900/50 bg-violet-950/30 px-2 py-1 text-violet-200/90">
            Markets: {(status?.search_symbols ?? ["MNQ", "NQ", "MES", "ES"]).join(" · ")}
          </span>
          <span className="rounded-full border border-zinc-700 px-2 py-1">Hourly: {status?.hourly_enabled ? "on" : "off"}</span>
          <span className="rounded-full border border-zinc-700 px-2 py-1">
            AI: {status?.ai_configured ? "OpenAI" : "rules"}
          </span>
          {status?.cycle_stats.last_cycle_detail ? (
            <span className="max-w-full truncate rounded-full border border-zinc-700 px-2 py-1">
              Last: {status.cycle_stats.last_cycle_detail}
            </span>
          ) : null}
        </div>
        <button
          type="button"
          disabled={running}
          onClick={runNow}
          className="mt-4 w-full rounded-lg bg-emerald-600 px-4 py-3.5 text-sm font-semibold text-white shadow-lg shadow-emerald-900/30 hover:bg-emerald-500 disabled:opacity-50 md:w-auto"
        >
          {running ? "Searching…" : "Run prop search"}
        </button>
        {note ? <p className="mt-3 text-sm text-zinc-400">{note}</p> : null}
      </section>

      <section>
        <div className="flex items-end justify-between gap-2">
          <h3 className="text-sm font-semibold text-zinc-100">Profitable candidates</h3>
          <Link href="/backtests" className="text-xs text-emerald-500 hover:underline">
            All results
          </Link>
        </div>
        <p className="mt-1 text-xs text-zinc-500">
          Must have net &gt; $0, profit factor ≥ 1.1, ≥8 trades, drawdown under ~$3.5k (on $100k sim).
        </p>
        {!candidates.length ? (
          <div className="mt-4 rounded-lg border border-dashed border-zinc-700 p-8 text-center text-sm text-zinc-500">
            No profitable setups yet. Tap <strong className="text-zinc-300">Run prop search</strong> — each run tests many
            combos across Nasdaq (MNQ, NQ) and S&amp;P (MES, ES).
          </div>
        ) : (
          <ul className="mt-4 space-y-4">
            {candidates.map((r) => (
              <LeaderboardCard key={r.run_id} row={r} />
            ))}
          </ul>
        )}
      </section>

      <section>
        <h3 className="text-sm font-medium text-zinc-200">Activity</h3>
        <ul className="mt-3 space-y-3">
          {(status?.recent_activity ?? []).slice(0, 6).map((a, i) => (
            <li key={i} className="border-b border-zinc-800/80 pb-2 text-sm">
              <p className="text-zinc-100">{a.headline}</p>
              {a.detail ? <p className="text-xs leading-relaxed text-zinc-500">{a.detail}</p> : null}
            </li>
          ))}
        </ul>
      </section>
    </div>
  );
}