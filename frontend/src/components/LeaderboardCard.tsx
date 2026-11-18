"use client";

import Link from "next/link";
import { useState } from "react";
import { apiFetch } from "@/lib/api";

export type LeaderboardEntry = {
  run_id: string;
  strategy_id: string;
  strategy_name: string;
  symbol: string;
  category: string;
  timeframe: string;
  origin?: string;
  completed_at?: string | null;
  tested_at?: string | null;
  passes_prop_screen?: boolean;
  gate_miss?: string | null;
  prop_ready_score: number;
  sample?: {
    start?: string | null;
    end?: string | null;
    bars?: number;
    days?: number | null;
    summary?: string;
  } | null;
  risk?: {
    stop_ticks?: number | null;
    target_ticks?: number | null;
    stop_usd?: number | null;
    dollar_risk_per_trade?: number | null;
    max_contracts?: number | null;
    max_drawdown_usd?: number | null;
    dd_pct_of_account?: number | null;
    avg_loss_usd?: number | null;
    summary?: string;
  } | null;
  tests?: {
    tested_at?: string | null;
    method?: string;
    oos_trades?: number | null;
    oos_win_rate_pct?: number | null;
    full_trades?: number | null;
    summary?: string;
  } | null;
  metrics: {
    net_profit_usd?: number;
    profit_factor?: number | null;
    trade_count?: number;
    win_rate_pct?: number | null;
    max_drawdown_usd?: number;
    expectancy_usd?: number | null;
    avg_win_usd?: number | null;
    avg_loss_usd?: number | null;
    robustness_pct?: number | null;
  };
};

function fmtUsd(n?: number | null) {
  if (n == null) return "—";
  const sign = n >= 0 ? "+" : "";
  return `${sign}$${Math.abs(n).toLocaleString(undefined, { maximumFractionDigits: 0 })}`;
}

function fmtLondon(iso?: string | null) {
  if (!iso) return null;
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return null;
  const stamp = new Intl.DateTimeFormat("en-GB", {
    timeZone: "Europe/London",
    day: "numeric",
    month: "short",
    year: "numeric",
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
  }).format(d);
  return `${stamp} London`;
}

function fmtRange(start?: string | null, end?: string | null) {
  if (!start || !end) return null;
  const opts: Intl.DateTimeFormatOptions = {
    timeZone: "Europe/London",
    day: "numeric",
    month: "short",
    year: "numeric",
  };
  const a = new Intl.DateTimeFormat("en-GB", opts).format(new Date(start));
  const b = new Intl.DateTimeFormat("en-GB", opts).format(new Date(end));
  return a === b ? a : `${a} – ${b}`;
}

export function LeaderboardCard({ row }: { row: LeaderboardEntry }) {
  const m = row.metrics;
  const reversed = row.origin === "reverse" || row.category.startsWith("reversed_");
  const nearMiss = row.origin === "near_miss";
  const keeper = row.passes_prop_screen === true || (row.prop_ready_score ?? 0) > 0;
  const lowHitRate = (m.win_rate_pct ?? 100) < 42;
  const swingStyle = lowHitRate && (m.net_profit_usd ?? 0) > 0;
  const [watchNote, setWatchNote] = useState<string | null>(null);
  const [watching, setWatching] = useState(false);

  async function watchLive() {
    setWatching(true);
    setWatchNote(null);
    try {
      await apiFetch("/api/v1/paper/enroll", {
        method: "POST",
        body: JSON.stringify({ strategy_id: row.strategy_id }),
      });
      setWatchNote("Enrolled on the forward-test book. Open Paper to track live fills.");
    } catch (e) {
      setWatchNote(String(e));
    } finally {
      setWatching(false);
    }
  }
  return (
    <li className="rounded-xl border border-zinc-800 bg-gradient-to-br from-[#1a1d26] to-[#14171e] p-4 shadow-lg">
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0 flex-1">
          <p className="text-xs font-medium uppercase tracking-wide text-emerald-500/90">
            {row.symbol} · {row.timeframe} · {row.category.replaceAll("_", " ")}
            {reversed ? " · reverse fade" : ""}
            {keeper && nearMiss ? " · full-sample keeper" : ""}
            {!keeper && (nearMiss || row.gate_miss) ? " · search gate miss" : ""}
            {swingStyle && row.prop_ready_score === 0 ? " · swing-style R:R" : ""}
          </p>
          <Link
            href={`/backtests/${row.run_id}`}
            className="mt-1 block truncate text-base font-semibold text-zinc-50 hover:text-emerald-400"
          >
            {row.strategy_name}
          </Link>
          {reversed ? (
            <p className="mt-1 text-[11px] text-violet-300/90">
              Faded anti-edge — original signal inverted, stop/target swapped, walk-forward re-tested.
            </p>
          ) : null}
          {fmtLondon(row.tested_at || row.completed_at || row.tests?.tested_at) ? (
            <p className="mt-1 text-[11px] text-zinc-400">
              Tested {fmtLondon(row.tested_at || row.completed_at || row.tests?.tested_at)}
              {row.sample?.summary ? ` · ${row.sample.summary}` : ""}
              {fmtRange(row.sample?.start, row.sample?.end) ? ` · ${fmtRange(row.sample?.start, row.sample?.end)}` : ""}
            </p>
          ) : row.sample?.summary ? (
            <p className="mt-1 text-[11px] text-zinc-400">{row.sample.summary}</p>
          ) : null}
        </div>
        <div className="shrink-0 text-right">
          {reversed ? (
            <p className="mb-1 rounded-full border border-violet-800/70 bg-violet-950/50 px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wide text-violet-200">
              Reverse
            </p>
          ) : null}
          <p className="text-[10px] uppercase text-zinc-500">Prop score</p>
          <p
            className={`text-lg font-bold tabular-nums ${row.prop_ready_score >= 60 ? "text-emerald-400" : row.prop_ready_score > 0 ? "text-amber-400" : "text-zinc-600"}`}
          >
            {row.prop_ready_score > 0 ? row.prop_ready_score : "—"}
          </p>
        </div>
      </div>
      {swingStyle ? (
        <p className="mt-3 text-[11px] leading-relaxed text-amber-200/90">
          Expectancy is average $ per trade (net P&amp;L ÷ trades). A low win rate can still be positive when
          winners are much larger than losers — that is wide R:R, not a typical intraday prop profile (keepers
          need ≥42% hit rate).
        </p>
      ) : null}
      {!keeper && row.gate_miss ? (
        <p className="mt-3 text-[11px] leading-relaxed text-amber-200/90">
          Not unprofitable — {row.gate_miss}. Keepers need enough trades in the sample, not just green P&amp;L.
        </p>
      ) : null}
      <dl className="mt-4 grid grid-cols-2 gap-3 text-xs sm:grid-cols-4">
        <Metric label="Net P&L" value={fmtUsd(m.net_profit_usd)} positive={(m.net_profit_usd ?? 0) > 0} />
        <Metric
          label="Profit factor"
          value={m.profit_factor != null ? m.profit_factor.toFixed(2) : "—"}
          positive={(m.profit_factor ?? 0) >= 1.1}
        />
        <Metric label="Trades" value={String(m.trade_count ?? "—")} />
        <Metric
          label="Win rate"
          value={m.win_rate_pct != null ? `${m.win_rate_pct}%` : "—"}
          positive={!lowHitRate}
        />
        <Metric label="Max DD" value={m.max_drawdown_usd != null ? fmtUsd(-m.max_drawdown_usd) : "—"} />
        <Metric label="Expectancy / trade" value={fmtUsd(m.expectancy_usd)} positive={(m.expectancy_usd ?? 0) > 0} />
        <Metric label="Avg win" value={fmtUsd(m.avg_win_usd)} positive />
        <Metric label="Avg loss" value={m.avg_loss_usd != null ? fmtUsd(-Math.abs(m.avg_loss_usd)) : "—"} positive={false} />
        <Metric
          label="Robust MC"
          value={m.robustness_pct != null ? `${m.robustness_pct}%` : "—"}
          positive={(m.robustness_pct ?? 0) >= 50}
        />
        <Metric
          label="Planned risk"
          value={
            row.risk?.dollar_risk_per_trade != null
              ? `$${row.risk.dollar_risk_per_trade.toFixed(0)} / trade`
              : row.risk?.stop_usd != null
                ? `$${row.risk.stop_usd.toFixed(0)} stop`
                : "—"
          }
        />
        <Metric
          label="Stop / target"
          value={
            row.risk?.stop_ticks != null && row.risk?.target_ticks != null
              ? `${row.risk.stop_ticks}/${row.risk.target_ticks} ticks`
              : "—"
          }
        />
        <Metric
          label="Contracts cap"
          value={row.risk?.max_contracts != null ? String(row.risk.max_contracts) : "—"}
        />
      </dl>
      {row.tests?.summary ? (
        <p className="mt-3 text-[11px] leading-relaxed text-zinc-400">{row.tests.summary}</p>
      ) : null}
      {row.risk?.summary ? (
        <p className="mt-1 text-[11px] leading-relaxed text-amber-100/90">
          Risk taken: {row.risk.summary}
        </p>
      ) : null}
      {keeper ? (
        <div className="mt-3 flex flex-wrap items-center gap-3">
          <button
            type="button"
            onClick={watchLive}
            disabled={watching}
            className="rounded-lg border border-emerald-700/60 bg-emerald-950/40 px-3 py-1.5 text-xs font-semibold text-emerald-200 hover:bg-emerald-900/50 disabled:opacity-50"
          >
            {watching ? "Enrolling…" : "Watch live"}
          </button>
          <Link href="/paper" className="text-xs text-emerald-500 hover:underline">
            Forward-test book
          </Link>
          {watchNote ? <p className="text-[11px] text-zinc-400">{watchNote}</p> : null}
        </div>
      ) : null}
    </li>
  );
}

function Metric({ label, value, positive }: { label: string; value: string; positive?: boolean }) {
  return (
    <div>
      <dt className="text-zinc-500">{label}</dt>
      <dd
        className={`font-medium tabular-nums ${positive === true ? "text-emerald-300" : positive === false ? "text-red-300" : "text-zinc-200"}`}
      >
        {value}
      </dd>
    </div>
  );
}