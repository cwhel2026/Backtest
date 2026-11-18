"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { LeaderboardCard, type LeaderboardEntry } from "@/components/LeaderboardCard";
import { SearchLiveMonitor } from "@/components/SearchLiveMonitor";
import { apiFetch } from "@/lib/api";

type BackgroundSearch = {
  job_id: string;
  status: string;
  message: string;
  progress_pct: number;
  started_at: string | null;
  error?: string | null;
  live?: Record<string, unknown> | null;
  job_log?: { headline: string; detail: string; created_at: string }[];
};

type SearchPlan = {
  symbols: string[];
  combos_per_symbol: number;
  history_days: number;
  families: string[];
  walk_forward: string;
  reverse_fades: boolean;
};

type PaperDesk = {
  account: {
    status: string;
    equity: number;
    day_pnl: number;
    trailing_room: number;
    distance_to_target: number;
  };
  enrolled: { slot_id: string; symbol: string; strategy_name: string; in_trade: boolean }[];
  open_positions: { slot_id: string; strategy_name: string; symbol: string; direction: string; quantity: number; entry_price: number }[];
};

type AutopilotStatus = {
  hourly_enabled: boolean;
  ai_configured: boolean;
  message: string;
  background_search: BackgroundSearch | null;
  profitable_candidates: LeaderboardEntry[];
  recent_tests: LeaderboardEntry[];
  recent_activity: { headline: string; detail: string; created_at: string }[];
  cycle_stats: { tests_run: number; profitable_count: number; last_cycle_detail: string | null };
  search_symbols: string[];
  search_plan: SearchPlan | null;
};

function compactSearchText(text: string | null | undefined): string {
  if (!text) return "";
  if (/diskfull|no space left|could not extend file/i.test(text)) {
    return "Postgres ran out of disk while loading 1m bars. Extra copies will be cleared on restart — press Restart search. If it happens again, increase the Railway Postgres volume.";
  }
  const cut = text.split("[SQL:")[0].split("[parameters:")[0].trim();
  return cut.length > 280 ? `${cut.slice(0, 280)}…` : cut;
}

export default function HomePage() {
  const [status, setStatus] = useState<AutopilotStatus | null>(null);
  const [paper, setPaper] = useState<PaperDesk | null>(null);
  const [running, setRunning] = useState(false);
  const [note, setNote] = useState<string | null>(null);

  function refresh() {
    apiFetch<AutopilotStatus>("/api/v1/autopilot/status").then(setStatus).catch((e) => setNote(String(e)));
    apiFetch<PaperDesk>("/api/v1/paper/desk").then(setPaper).catch(() => undefined);
  }

  useEffect(() => {
    refresh();
    return () => undefined;
  }, []);

  useEffect(() => {
    const busy = status?.background_search?.status === "queued" || status?.background_search?.status === "running";
    const ms = busy ? 4000 : 15000;
    const t = setInterval(refresh, ms);
    return () => clearInterval(t);
  }, [status?.background_search?.status]);

  async function runNow() {
    setRunning(true);
    setNote(null);
    try {
      const res = await apiFetch<{ status: string; mode: string; job_id: string | null }>(
        `/api/v1/autopilot/run${searching ? "?restart=true" : ""}`,
        { method: "POST" }
      );
      if (res.mode === "already_active") {
        setNote("One search is still scoring. Use Restart search if it has stopped updating.");
      } else {
        setNote("Search started on the server. The status line below updates as each market is scored. You can leave this page.");
      }
      setTimeout(refresh, 5000);
    } catch (e) {
      setNote(String(e));
    } finally {
      setRunning(false);
    }
  }

  const candidates = status?.profitable_candidates ?? [];
  const latestTests = (status?.recent_tests ?? []).filter((row) => !candidates.some((c) => c.run_id === row.run_id));
  const searching =
    status?.background_search?.status === "queued" || status?.background_search?.status === "running";

  return (
    <div className="space-y-8">
      <header>
        <h2 className="page-title">Prop desk</h2>
        <p className="page-sub">
          Search runs on the server, keepers are backtested walk-forward, then the paper book takes the next trades.
        </p>
      </header>

      <ol className="grid gap-3 md:grid-cols-3">
        <li className="rounded-xl border border-zinc-800 bg-[#181b22] p-4">
          <p className="text-[10px] font-semibold uppercase tracking-wider text-emerald-400">1 · Search</p>
          <p className="mt-2 text-sm text-zinc-200">
            {status?.background_search ? "Running now" : status?.hourly_enabled ? "Hourly, even if you leave" : "Manual"}
          </p>
          <p className="mt-1 text-xs text-zinc-500">Nasdaq + S&P, including reverse fades.</p>
        </li>
        <li className="rounded-xl border border-zinc-800 bg-[#181b22] p-4">
          <p className="text-[10px] font-semibold uppercase tracking-wider text-emerald-400">2 · Backtest</p>
          <p className="mt-2 text-sm text-zinc-200">{candidates.length} profitable keepers</p>
          <p className="mt-1 text-xs text-zinc-500">Train, out-of-sample, then full sample.</p>
        </li>
        <li className="rounded-xl border border-zinc-800 bg-[#181b22] p-4">
          <p className="text-[10px] font-semibold uppercase tracking-wider text-emerald-400">3 · Forward test</p>
          <p className="mt-2 text-sm text-zinc-200">
            {paper ? `$${paper.account.equity.toLocaleString(undefined, { maximumFractionDigits: 0 })} · ${paper.account.status}` : "Paper book"}
          </p>
          <p className="mt-1 text-xs text-zinc-500">
            {paper ? `${paper.open_positions.length} open · ${paper.enrolled.length} enrolled` : "New bars every 5 minutes"}
          </p>
        </li>
      </ol>

      <section className="rounded-xl border border-emerald-900/50 bg-gradient-to-r from-emerald-950/40 to-[#181b22] p-4 md:p-6">
        <p className="text-sm leading-relaxed text-zinc-200">{status?.message}</p>
        <div className="mt-3 flex flex-wrap gap-2 text-xs text-zinc-400">
          <span className="rounded-full border border-violet-900/50 bg-violet-950/30 px-2 py-1 text-violet-200/90">
            Markets: {(status?.search_symbols ?? ["MNQ", "NQ", "MES", "ES"]).join(" · ")}
          </span>
          {status?.background_search ? (
            <span
              className={`rounded-full border px-2 py-1 ${
                status.background_search.status === "failed"
                  ? "border-red-900/70 bg-red-950/40 text-red-200"
                  : status.background_search.status === "completed"
                    ? "border-emerald-900/60 bg-emerald-950/30 text-emerald-200"
                    : "border-amber-800/60 bg-amber-950/40 text-amber-200"
              }`}
            >
              {status.background_search.status === "failed"
                ? compactSearchText(status.background_search.error || status.background_search.message)
                : `${status.background_search.status}: ${compactSearchText(status.background_search.message)}`}
            </span>
          ) : null}
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
          {running ? "Starting…" : searching ? "Restart search" : "Run prop search"}
        </button>
        {searching ? (
          <p className="mt-3 text-sm text-amber-100">
            A search is already in progress on the server. Current step:{" "}
            {compactSearchText(status?.background_search?.message)}
          </p>
        ) : status?.background_search?.status === "failed" ? (
          <p className="mt-3 text-sm text-amber-100">
            {compactSearchText(status.background_search.error) || "The last search stopped."} Press the green
            button to start a new one.
          </p>
        ) : null}
        {note ? <p className="mt-3 text-sm text-zinc-400">{note}</p> : null}
      </section>

      <SearchLiveMonitor
        status={status?.background_search?.status ?? "idle"}
        message={
          compactSearchText(status?.background_search?.message) ||
          "Press Run prop search to start a walk-forward scan."
        }
        progressPct={status?.background_search?.progress_pct ?? 0}
        live={(status?.background_search?.live as Record<string, unknown> | undefined) ?? null}
        plan={status?.search_plan ?? null}
        jobLog={status?.background_search?.job_log ?? []}
        active={searching}
      />

      {paper && paper.open_positions.length > 0 ? (
        <section>
          <div className="flex items-end justify-between">
            <h3 className="text-sm font-semibold text-zinc-100">Open paper trades</h3>
            <Link href="/paper" className="text-xs text-emerald-500 hover:underline">
              Prop book
            </Link>
          </div>
          <ul className="mt-3 space-y-2">
            {paper.open_positions.map((p) => (
              <li key={p.slot_id} className="flex items-center justify-between rounded-lg border border-zinc-800 px-3 py-2 text-sm">
                <span>
                  {p.symbol} {p.direction} ×{p.quantity}
                  <span className="ml-2 text-zinc-500">{p.strategy_name}</span>
                </span>
                <span className="tabular-nums text-zinc-300">{p.entry_price}</span>
              </li>
            ))}
          </ul>
        </section>
      ) : null}

      <section>
        <div className="flex items-end justify-between gap-2">
          <h3 className="text-sm font-semibold text-zinc-100">Profitable candidates</h3>
          <Link href="/backtests" className="text-xs text-emerald-500 hover:underline">
            All results
          </Link>
        </div>
        <p className="mt-1 text-xs text-zinc-500">
          Keepers: net &gt; $0, PF ≥ 1.1, ≥8 trades, win rate ≥ 42%, DD under ~$3.5k. Expectancy is net ÷
          trades (can be positive even with a low hit rate if winners are huge). Reverse fades use separate
          rules.
        </p>
        {searching ? (
          <p className="mt-4 text-sm text-amber-200/90">
            Search is running on the server. This list fills as each market finishes — you can leave the page.
          </p>
        ) : null}
        {!candidates.length ? (
          <div className="mt-4 rounded-lg border border-dashed border-zinc-700 p-8 text-center text-sm text-zinc-500">
            {searching
              ? "No keepers yet. The search log above updates per market (MNQ, NQ, MES, ES)."
              : "No prop-ready setups yet. Latest tests below still show what the search scored."}
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
        <h3 className="text-sm font-semibold text-zinc-100">Latest tests</h3>
        <p className="mt-1 text-xs text-zinc-500">
          Includes close calls that did not pass the prop screen, so a finished search is never a blank page.
        </p>
        {!latestTests.length ? (
          <p className="mt-3 text-sm text-zinc-500">
            {searching ? "Waiting for the first market to finish scoring." : "Nothing saved yet."}
          </p>
        ) : (
          <ul className="mt-4 space-y-4">
            {latestTests.map((r) => (
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