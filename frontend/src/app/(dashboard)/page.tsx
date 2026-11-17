"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { apiFetch } from "@/lib/api";

type AutopilotStatus = {
  hourly_enabled: boolean;
  ai_configured: boolean;
  message: string;
  top_backtests: {
    id: string;
    strategy_id: string;
    profit_factor?: number;
    net_profit?: number;
    trade_count?: number;
  }[];
  recent_activity: { headline: string; detail: string; created_at: string }[];
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
          ? "Cycle started on server — refresh in a minute for results."
          : "Cycle queued — watch activity below."
      );
      setTimeout(refresh, 3000);
    } catch (e) {
      setNote(String(e));
    } finally {
      setRunning(false);
    }
  }

  return (
    <div className="space-y-8">
      <header>
        <h2 className="page-title">Prop firm autopilot</h2>
        <p className="page-sub">
          Finds and backtests strategies on MES/MNQ using free market data, then simulates on the latest bars — no live
          broker.
        </p>
      </header>

      <section className="rounded-lg border border-emerald-900/40 bg-emerald-950/20 p-4 md:p-6">
        <p className="text-sm leading-relaxed text-zinc-300">{status?.message}</p>
        <p className="mt-2 text-xs text-zinc-500">
          Hourly search: {status?.hourly_enabled ? "on" : "off"} · AI:{" "}
          {status?.ai_configured ? "OpenAI" : "built-in rules (no key needed)"}
        </p>
        <button
          type="button"
          disabled={running}
          onClick={runNow}
          className="mt-4 w-full rounded-md bg-emerald-600 px-4 py-3 text-sm font-medium text-white hover:bg-emerald-500 disabled:opacity-50 md:w-auto md:py-2"
        >
          {running ? "Starting…" : "Run search now"}
        </button>
        {note ? <p className="mt-3 text-sm text-zinc-400">{note}</p> : null}
      </section>

      <section>
        <h3 className="text-sm font-medium text-zinc-200">Best backtests so far</h3>
        {!status?.top_backtests.length ? (
          <p className="mt-2 text-sm text-zinc-500">None yet — tap Run search now.</p>
        ) : (
          <ul className="mt-3 space-y-2">
            {status.top_backtests.map((r) => (
              <li key={r.id} className="rounded-lg border border-zinc-800 bg-[#181b22] px-4 py-3 text-sm">
                <Link href={`/backtests/${r.id}`} className="font-medium text-emerald-400 hover:underline">
                  Run {r.id.slice(0, 8)}
                </Link>
                <span className="ml-2 text-zinc-500">
                  PF {r.profit_factor ?? "—"} · net {r.net_profit ?? "—"} · {r.trade_count ?? 0} trades
                </span>
              </li>
            ))}
          </ul>
        )}
      </section>

      <section>
        <h3 className="text-sm font-medium text-zinc-200">What the bot did</h3>
        <ul className="mt-3 space-y-3">
          {(status?.recent_activity ?? []).map((a, i) => (
            <li key={i} className="border-b border-zinc-800/80 pb-2 text-sm">
              <p className="text-zinc-100">{a.headline}</p>
              {a.detail ? <p className="text-xs text-zinc-500">{a.detail}</p> : null}
            </li>
          ))}
        </ul>
      </section>

      <p className="text-xs text-zinc-600">
        Advanced:{" "}
        <Link href="/backtests" className="text-zinc-400 underline">
          all backtests
        </Link>
      </p>
    </div>
  );
}