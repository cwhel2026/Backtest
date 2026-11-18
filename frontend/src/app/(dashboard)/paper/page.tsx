"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { apiFetch } from "@/lib/api";

type Fill = {
  id: string;
  strategy_name: string;
  symbol: string;
  direction: string;
  quantity: number;
  exit_reason: string;
  net_pnl: number;
  exit_ts: string;
};

type Enrolled = {
  slot_id: string;
  symbol: string;
  timeframe?: string;
  strategy_name: string;
  in_trade: boolean;
  direction?: string | null;
  quantity?: number;
  entry_price?: number | null;
  stop?: number | null;
  target?: number | null;
  state?: string;
  paper_trades?: number;
  paper_net?: number;
  paper_win_rate_pct?: number | null;
  last_bar_ts?: string | null;
  last_refresh_at?: string | null;
  last_error?: string | null;
  last_open?: number | null;
  last_high?: number | null;
  last_low?: number | null;
  last_close?: number | null;
  last_volume?: number | null;
  bar_age_sec?: number | null;
  bars_in_dataset?: number;
  feed_source?: string | null;
  next_bar_sec?: number | null;
  caught_up?: boolean;
  armed?: boolean;
  new_bars?: number;
  unrealized?: number | null;
  baseline?: { net: number; win_rate_pct: number | null; trades: number; expectancy: number | null } | null;
};

type ScanHistory = {
  at: string;
  headline: string;
  opened: number;
  closed: number;
  refreshed: number;
  enrolled_new: number;
  new_bars: number;
  slots: number;
};

type Scanner = {
  status: string;
  live: boolean;
  stale: boolean;
  tick_interval_sec: number;
  last_scan_at?: string | null;
  last_scan_age_sec?: number | null;
  next_scan_sec?: number | null;
  headline: string;
  session: { state: string; label: string; open: boolean; chicago: string; weekday?: string };
  opened: number;
  closed: number;
  refreshed: number;
  enrolled_new: number;
  new_bars: number;
  history: ScanHistory[];
  watching_count: number;
  in_trade_count: number;
  slot_count: number;
  feed_note: string;
};

type Desk = {
  disclaimer: string;
  heartbeat?: string;
  scanner?: Scanner;
  account: {
    name: string;
    status: string;
    equity: number;
    starting_equity: number;
    day_pnl: number;
    daily_loss_limit: number;
    trailing_room: number;
    distance_to_target: number;
    profit_target: number;
  };
  enrolled: Enrolled[];
  open_positions: {
    slot_id: string;
    strategy_name: string;
    symbol: string;
    direction: string;
    quantity: number;
    entry_price: number;
    stop: number;
    target: number;
    timeframe?: string;
    bars_held?: number;
    last_close?: number | null;
    unrealized?: number | null;
    last_bar_ts?: string | null;
  }[];
  recent_fills: Fill[];
};

function money(n: number) {
  const sign = n > 0 ? "+" : "";
  return `${sign}$${n.toLocaleString(undefined, { maximumFractionDigits: 0 })}`;
}

function px(n: number | null | undefined) {
  if (n == null || Number.isNaN(n)) return "—";
  return n.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 });
}

function chicagoClock(iso?: string | null) {
  if (!iso) return "—";
  const t = Date.parse(iso);
  if (Number.isNaN(t)) return "—";
  return (
    new Date(t).toLocaleString("en-GB", {
      timeZone: "America/Chicago",
      hour: "2-digit",
      minute: "2-digit",
      second: "2-digit",
      hour12: false,
    }) + " CT"
  );
}

function ageLabel(seconds: number | null | undefined) {
  if (seconds == null) return "never";
  if (seconds < 5) return "just now";
  if (seconds < 60) return `${seconds}s ago`;
  const mins = Math.floor(seconds / 60);
  if (mins < 60) return `${mins}m ago`;
  return `${Math.floor(mins / 60)}h ${mins % 60}m ago`;
}

function delayNote(barAgeSec: number | null | undefined, sessionOpen: boolean) {
  if (barAgeSec == null) return "Waiting for the first print.";
  if (!sessionOpen && barAgeSec > 30 * 60) return "Market closed — last print from the prior session.";
  if (barAgeSec < 90) return "Fresh print.";
  if (barAgeSec < 20 * 60) return "Delayed feed (~15m Yahoo/FinzData) — still scanning each new bar.";
  return "Feed lag is larger than usual. Press Scan now if this stays stuck.";
}

function slotStatus(slot: Enrolled) {
  if (slot.last_error) return { label: "Feed error", tone: "text-red-300", ring: "border-red-900/60" };
  if (slot.in_trade) return { label: "In trade", tone: "text-amber-200", ring: "border-amber-800/70" };
  if (slot.armed) return { label: "Armed — waiting for next bar", tone: "text-emerald-300", ring: "border-emerald-800/60" };
  if (slot.state === "scanned" || (slot.new_bars && slot.new_bars > 0))
    return { label: "Just scanned — no entry", tone: "text-emerald-200", ring: "border-emerald-900/50" };
  return { label: "Scanning for entries", tone: "text-emerald-300", ring: "border-emerald-900/40" };
}

export default function PaperTradingPage() {
  const [desk, setDesk] = useState<Desk | null>(null);
  const [note, setNote] = useState<string | null>(null);
  const [scanning, setScanning] = useState(false);
  const [now, setNow] = useState(() => Date.now());
  const [lastPassAt, setLastPassAt] = useState<number | null>(null);
  const inFlight = useRef(false);

  const load = useCallback(() => {
    apiFetch<Desk>("/api/v1/paper/desk")
      .then(setDesk)
      .catch((e) => setNote(String(e)));
  }, []);

  const tick = useCallback(async (reason: "auto" | "manual") => {
    if (inFlight.current) return;
    inFlight.current = true;
    setScanning(true);
    if (reason === "manual") setNote(null);
    try {
      const res = await apiFetch<{
        tick: {
          opened: number;
          closed: number;
          refreshed: number;
          enrolled_new?: number;
          headline?: string;
          watches?: { new_bars?: number; symbol?: string; timeframe?: string }[];
        };
        desk: Desk;
      }>("/api/v1/paper/tick", { method: "POST" });
      setDesk(res.desk);
      setLastPassAt(Date.now());
      const newBars = (res.tick.watches ?? []).reduce((n, w) => n + (w.new_bars ?? 0), 0);
      setNote(
        res.tick.headline ||
          `Scan pass: ${res.tick.refreshed ?? 0} feeds, ${newBars} new bars, ${res.tick.opened} entries, ${res.tick.closed} exits.`,
      );
    } catch (e) {
      setNote(String(e));
    } finally {
      inFlight.current = false;
      setScanning(false);
    }
  }, []);

  useEffect(() => {
    load();
    void tick("auto");
    const poll = setInterval(load, 4000);
    const scan = setInterval(() => void tick("auto"), 30000);
    const clock = setInterval(() => setNow(Date.now()), 1000);
    return () => {
      clearInterval(poll);
      clearInterval(scan);
      clearInterval(clock);
    };
  }, [load, tick]);

  const account = desk?.account;
  const scanner = desk?.scanner;
  const sessionOpen = scanner?.session?.open !== false;
  const scanAge =
    lastPassAt != null
      ? Math.max(0, Math.floor((now - lastPassAt) / 1000))
      : scanner?.last_scan_age_sec ?? null;
  const live = scanning || (scanAge != null && scanAge <= 90);
  const statusLabel = scanning
    ? "Scanning now"
    : scanner?.status === "in_trade"
      ? "In trade · still scanning"
      : scanner?.status === "empty"
        ? "Arming book"
        : scanner?.status === "stale"
          ? "Scan stale"
          : scanner?.status === "error"
            ? "Feed error"
            : live
              ? "Live · scanning for trades"
              : "Armed";

  return (
    <div className="space-y-8">
      <header className="flex flex-col gap-3 md:flex-row md:items-end md:justify-between">
        <div>
          <h2 className="page-title">Forward test</h2>
          <p className="page-sub max-w-2xl">
            Keepers (including NQ 1m ATR pullbacks) sit on this book. The worker scans every minute; this
            page also pulls a pass when you open it so you can watch last prints, new bars, and entries.
          </p>
        </div>
        <button
          type="button"
          onClick={() => void tick("manual")}
          disabled={scanning}
          className="rounded-lg bg-emerald-600 px-4 py-2.5 text-sm font-semibold text-white hover:bg-emerald-500 disabled:opacity-60"
        >
          {scanning ? "Scanning…" : "Scan now"}
        </button>
      </header>

      <section
        className={`overflow-hidden rounded-2xl border bg-[#141820] ${
          live ? "border-emerald-800/70" : scanner?.stale ? "border-amber-800/70" : "border-zinc-800"
        }`}
      >
        <div className="relative h-1 overflow-hidden bg-zinc-900">
          <div
            className={`h-full w-1/3 bg-gradient-to-r from-transparent via-emerald-400 to-transparent ${
              scanning || live ? "scan-sweep" : ""
            }`}
          />
        </div>
        <div className="p-5">
          <div className="flex flex-col gap-3 md:flex-row md:items-start md:justify-between">
            <div className="flex items-start gap-3">
              <span
                className={`mt-1 inline-block h-3 w-3 rounded-full ${
                  scanning || live ? "scan-dot bg-emerald-400" : scanner?.stale ? "bg-amber-400" : "bg-zinc-500"
                }`}
              />
              <div>
                <p className="text-[11px] font-semibold uppercase tracking-[0.18em] text-emerald-400">
                  Live scanner
                </p>
                <p className="mt-1 text-lg font-semibold text-zinc-50">{statusLabel}</p>
                <p className="mt-1 max-w-2xl text-sm text-zinc-300">
                  {scanning
                    ? "Pulling delayed live bars and evaluating every enrolled setup for an entry or exit."
                    : scanner?.headline || "Opening the book and waiting for the first scan pass."}
                </p>
              </div>
            </div>
            <div className="text-right text-xs text-zinc-500">
              <p>{scanner?.session?.label ?? "CME Globex"}</p>
              <p className="mt-0.5 tabular-nums text-zinc-300">{scanner?.session?.chicago ?? ""}</p>
              <p className="mt-1">Last pass {ageLabel(scanAge)}</p>
            </div>
          </div>

          <dl className="mt-5 grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
            <ScanStat
              label="Watching"
              value={`${scanner?.watching_count ?? desk?.enrolled.length ?? 0} setups`}
              hint={`${scanner?.slot_count ?? 0} enrolled · ${scanner?.in_trade_count ?? 0} in trade`}
            />
            <ScanStat
              label="This pass"
              value={`${scanner?.new_bars ?? 0} new bars`}
              hint={`${scanner?.refreshed ?? 0} feeds · ${scanner?.opened ?? 0} entries · ${scanner?.closed ?? 0} exits`}
            />
            <ScanStat
              label="Worker"
              value={`every ${scanner?.tick_interval_sec ?? 60}s`}
              hint={
                scanning
                  ? "Pass in flight"
                  : scanner?.next_scan_sec != null
                    ? `Next worker pass ~${scanner.next_scan_sec}s`
                    : "Page also scans every 30s while open"
              }
            />
            <ScanStat
              label="Last print"
              value={
                desk?.enrolled.find((s) => s.last_close != null)
                  ? `${desk.enrolled.find((s) => s.last_close != null)?.symbol} ${px(
                      desk.enrolled.find((s) => s.last_close != null)?.last_close,
                    )}`
                  : "—"
              }
              hint={
                desk?.enrolled.find((s) => s.last_bar_ts)
                  ? `${chicagoClock(desk.enrolled.find((s) => s.last_bar_ts)?.last_bar_ts)} · ${delayNote(
                      desk.enrolled.find((s) => s.bar_age_sec != null)?.bar_age_sec,
                      sessionOpen,
                    )}`
                  : "No bars yet"
              }
            />
          </dl>
          <p className="mt-4 text-xs text-zinc-500">{scanner?.feed_note}</p>
        </div>
      </section>

      {note ? (
        <p className={`text-sm ${note.startsWith("Feed") || note.includes("error") ? "text-red-300" : "text-zinc-400"}`}>
          {note}
        </p>
      ) : null}

      {account ? (
        <section className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
          <Stat label="Equity" value={money(account.equity)} hint={account.status} />
          <Stat label="Today" value={money(account.day_pnl)} hint={`Daily stop ${money(-account.daily_loss_limit)}`} />
          <Stat label="Trailing room" value={money(account.trailing_room)} hint="Before max drawdown" />
          <Stat label="To target" value={money(account.distance_to_target)} hint={`Target ${money(account.profit_target)}`} />
        </section>
      ) : null}

      <section>
        <h3 className="text-sm font-semibold text-zinc-100">Open trades</h3>
        {!desk?.open_positions.length ? (
          <p className="mt-3 text-sm text-zinc-500">
            Flat. The book does not replay history — it waits for the next live bar after it is armed, then
            scans that bar for the same DSL entry used in the backtest.
          </p>
        ) : (
          <ul className="mt-3 space-y-2">
            {desk.open_positions.map((p) => (
              <li key={p.slot_id} className="rounded-xl border border-amber-900/50 bg-[#181b22] p-4 text-sm">
                <div className="flex items-start justify-between gap-3">
                  <div>
                    <p className="font-medium text-zinc-50">
                      {p.symbol} {p.timeframe ?? ""} {p.direction.toUpperCase()} ×{p.quantity}
                    </p>
                    <p className="text-zinc-400">{p.strategy_name}</p>
                  </div>
                  <span className={`tabular-nums font-semibold ${ (p.unrealized ?? 0) >= 0 ? "text-emerald-300" : "text-red-300"}`}>
                    {p.unrealized != null ? money(p.unrealized) : "—"}
                  </span>
                </div>
                <p className="mt-2 text-xs text-zinc-500">
                  Entry {px(p.entry_price)} · last {px(p.last_close)} · stop {px(p.stop)} · target {px(p.target)}
                  {p.bars_held ? ` · held ${p.bars_held} bars` : ""}
                </p>
              </li>
            ))}
          </ul>
        )}
      </section>

      <section>
        <div className="flex items-end justify-between gap-2">
          <h3 className="text-sm font-semibold text-zinc-100">Strategies being scanned</h3>
          <p className="text-xs text-zinc-500">{desk?.enrolled.length ?? 0} live slots</p>
        </div>
        <ul className="mt-3 space-y-3">
          {(desk?.enrolled ?? []).map((s) => {
            const st = slotStatus(s);
            return (
              <li key={s.slot_id} className={`rounded-xl border bg-[#181b22] px-4 py-3 text-sm ${st.ring}`}>
                <div className="flex flex-col gap-2 md:flex-row md:items-start md:justify-between">
                  <div>
                    <p className="font-medium text-zinc-100">
                      {s.strategy_name}
                      <span className="ml-2 text-xs font-normal text-zinc-500">
                        {s.symbol} {s.timeframe}
                      </span>
                    </p>
                    <p className={`mt-1 text-xs font-medium uppercase tracking-wide ${st.tone}`}>{st.label}</p>
                  </div>
                  <div className="text-right">
                    <p className="font-mono text-lg tabular-nums text-zinc-50">{px(s.last_close)}</p>
                    <p className="text-[11px] text-zinc-500">{chicagoClock(s.last_bar_ts)}</p>
                  </div>
                </div>
                <p className="mt-2 text-xs text-zinc-500">
                  O {px(s.last_open)} · H {px(s.last_high)} · L {px(s.last_low)} · vol{" "}
                  {(s.last_volume ?? 0).toLocaleString()}
                  {s.bars_in_dataset ? ` · ${s.bars_in_dataset.toLocaleString()} bars in feed` : ""}
                  {s.new_bars ? ` · ${s.new_bars} new this pass` : ""}
                </p>
                <p className="mt-1 text-xs text-zinc-500">
                  {s.armed
                    ? "Cursor armed on the latest bar. The next new 1m/5m print will be evaluated for an entry."
                    : s.caught_up
                      ? `Caught up. Next ${s.timeframe} bar expected in ~${s.next_bar_sec ?? "?"}s (plus feed delay).`
                      : "Evaluating new bars as they land."}{" "}
                  Live {s.paper_trades ?? 0} fills · {money(s.paper_net ?? 0)}
                  {s.paper_win_rate_pct != null ? ` · ${s.paper_win_rate_pct}% WR` : ""}
                  {s.baseline ? ` · backtest ${money(s.baseline.net)} / ${s.baseline.trades} trades` : ""}
                </p>
                {s.feed_source ? <p className="mt-1 text-[11px] text-zinc-600">Feed {s.feed_source}</p> : null}
                {s.last_error ? <p className="mt-1 text-xs text-red-300">{s.last_error}</p> : null}
              </li>
            );
          })}
          {!desk?.enrolled.length ? (
            <li className="rounded-xl border border-dashed border-zinc-700 p-6 text-sm text-zinc-500">
              {scanning
                ? "Scan in progress — auto-enrolling keepers from the leaderboard."
                : "None yet. This page auto-enrolls keepers on the first scan, or press Watch live on a result card."}
            </li>
          ) : null}
        </ul>
      </section>

      <section>
        <h3 className="text-sm font-semibold text-zinc-100">Scan log</h3>
        <ul className="mt-3 space-y-2">
          {(scanner?.history ?? []).map((h, i) => (
            <li key={`${h.at}-${i}`} className="rounded-lg border border-zinc-800 px-3 py-2 text-sm">
              <div className="flex items-start justify-between gap-3">
                <p className="text-zinc-200">{h.headline}</p>
                <span className="shrink-0 text-[11px] tabular-nums text-zinc-500">{chicagoClock(h.at)}</span>
              </div>
              <p className="mt-1 text-xs text-zinc-500">
                {h.new_bars} new bars · {h.refreshed} feeds · {h.opened} entries · {h.closed} exits
                {h.enrolled_new ? ` · +${h.enrolled_new} enrolled` : ""}
              </p>
            </li>
          ))}
          {!scanner?.history?.length ? (
            <li className="text-sm text-zinc-500">
              {scanning ? "First pass is running…" : "No scan pass recorded yet. One starts as soon as this page opens."}
            </li>
          ) : null}
        </ul>
      </section>

      <section>
        <h3 className="text-sm font-semibold text-zinc-100">Fills</h3>
        <ul className="mt-3 space-y-2">
          {(desk?.recent_fills ?? []).map((f) => (
            <li key={f.id} className="flex items-center justify-between rounded-lg border border-zinc-800 px-3 py-2 text-sm">
              <span>
                {f.symbol} {f.direction} · {f.exit_reason}
                <span className="ml-2 text-zinc-500">{f.strategy_name}</span>
              </span>
              <span className={f.net_pnl >= 0 ? "text-emerald-300" : "text-red-300"}>{money(f.net_pnl)}</span>
            </li>
          ))}
          {!desk?.recent_fills.length ? <li className="text-sm text-zinc-500">No closed paper trades yet.</li> : null}
        </ul>
      </section>

      <p className="text-xs text-zinc-500">{desk?.disclaimer}</p>
    </div>
  );
}

function Stat({ label, value, hint }: { label: string; value: string; hint: string }) {
  return (
    <div className="rounded-xl border border-zinc-800 bg-[#181b22] p-4">
      <p className="text-[10px] uppercase tracking-wider text-zinc-500">{label}</p>
      <p className="mt-1 text-xl font-semibold tabular-nums text-zinc-50">{value}</p>
      <p className="mt-1 text-xs text-zinc-500">{hint}</p>
    </div>
  );
}

function ScanStat({ label, value, hint }: { label: string; value: string; hint: string }) {
  return (
    <div className="rounded-lg border border-zinc-800 bg-zinc-900/50 p-3">
      <p className="text-[10px] uppercase tracking-wider text-zinc-500">{label}</p>
      <p className="mt-1 text-sm font-semibold text-zinc-100">{value}</p>
      <p className="mt-1 text-[11px] leading-snug text-zinc-500">{hint}</p>
    </div>
  );
}
