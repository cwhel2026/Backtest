"use client";

import { useEffect, useState } from "react";
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

type Desk = {
  disclaimer: string;
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
  enrolled: { slot_id: string; symbol: string; strategy_name: string; in_trade: boolean }[];
  open_positions: {
    slot_id: string;
    strategy_name: string;
    symbol: string;
    direction: string;
    quantity: number;
    entry_price: number;
    stop: number;
    target: number;
  }[];
  recent_fills: Fill[];
};

function money(n: number) {
  const sign = n > 0 ? "+" : "";
  return `${sign}$${n.toLocaleString(undefined, { maximumFractionDigits: 0 })}`;
}

export default function PaperTradingPage() {
  const [desk, setDesk] = useState<Desk | null>(null);
  const [note, setNote] = useState<string | null>(null);

  function load() {
    apiFetch<Desk>("/api/v1/paper/desk").then(setDesk).catch((e) => setNote(String(e)));
  }

  useEffect(() => {
    load();
    const t = setInterval(load, 15000);
    return () => clearInterval(t);
  }, []);

  async function tick() {
    setNote(null);
    try {
      const res = await apiFetch<{ desk: Desk }>("/api/v1/paper/tick", { method: "POST" });
      setDesk(res.desk);
      setNote("Checked the latest bars and updated the paper book.");
    } catch (e) {
      setNote(String(e));
    }
  }

  const account = desk?.account;

  return (
    <div className="space-y-8">
      <header className="flex flex-col gap-3 md:flex-row md:items-end md:justify-between">
        <div>
          <h2 className="page-title">Forward test</h2>
          <p className="page-sub max-w-2xl">
            Walk-forward winners are enrolled here. Every few minutes the worker reads new bars and
            places simulated entries, stops, and targets under prop-style limits.
          </p>
        </div>
        <button
          type="button"
          onClick={tick}
          className="rounded-lg bg-emerald-600 px-4 py-2.5 text-sm font-semibold text-white hover:bg-emerald-500"
        >
          Update from latest bars
        </button>
      </header>

      {note ? <p className="text-sm text-zinc-400">{note}</p> : null}

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
            Flat. Enrolled strategies wait for the next signal on a new bar — history is not replayed.
          </p>
        ) : (
          <ul className="mt-3 space-y-2">
            {desk.open_positions.map((p) => (
              <li key={p.slot_id} className="rounded-xl border border-zinc-800 bg-[#181b22] p-4 text-sm">
                <p className="font-medium text-zinc-50">
                  {p.symbol} {p.direction.toUpperCase()} ×{p.quantity}
                </p>
                <p className="text-zinc-400">{p.strategy_name}</p>
                <p className="mt-2 text-xs text-zinc-500">
                  Entry {p.entry_price} · stop {p.stop} · target {p.target}
                </p>
              </li>
            ))}
          </ul>
        )}
      </section>

      <section>
        <h3 className="text-sm font-semibold text-zinc-100">Enrolled strategies</h3>
        <ul className="mt-3 space-y-2">
          {(desk?.enrolled ?? []).map((s) => (
            <li key={s.slot_id} className="flex justify-between rounded-lg border border-zinc-800 px-3 py-2 text-sm">
              <span>{s.strategy_name}</span>
              <span className="text-zinc-500">{s.in_trade ? "In trade" : s.symbol}</span>
            </li>
          ))}
          {!desk?.enrolled.length ? <li className="text-sm text-zinc-500">None yet. Run a prop search first.</li> : null}
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
