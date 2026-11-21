"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { Card } from "@/components/ui/Card";
import { EmptyState } from "@/components/ui/EmptyState";
import { Skeleton } from "@/components/ui/Skeleton";
import { apiFetch } from "@/lib/api";

type Researcher = {
  id: string;
  provider_slug: string;
  display_name: string;
  enabled: boolean;
  activated_by_user: boolean;
  connection_status: string;
  model_id: string;
  current_activity: string;
  last_cycle_at: string | null;
  stats: Record<string, number>;
  daily_spend_usd: number;
  monthly_spend_usd: number;
  experiments_by_status: Record<string, number>;
};

type Arena = {
  researchers: Researcher[];
  leaderboard: {
    provider_slug: string;
    family: string;
    net_pnl: number;
    trade_count: number;
  }[];
  provider_catalog: { slug: string; env_var: string; key_configured: boolean; default_model: string }[];
};

export default function AiArenaPage() {
  const [arena, setArena] = useState<Arena | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    apiFetch<Arena>("/api/v1/ai-arena")
      .then(setArena)
      .catch(() => setArena(null))
      .finally(() => setLoading(false));
  }, []);

  async function triggerCycle(slug: string) {
    await apiFetch(`/api/v1/ai-arena/researchers/${slug}/run-cycle`, { method: "POST" });
    const fresh = await apiFetch<Arena>("/api/v1/ai-arena");
    setArena(fresh);
  }

  return (
    <div className="space-y-6 pb-10">
      <header>
        <h1 className="page-title">AI Research Arena</h1>
        <p className="page-sub">
          Eight independent LLM researchers compete under statistical validation — no live orders, no fabricated results.
        </p>
      </header>

      <Card className="panel text-sm text-zinc-400">
        API keys live only on the server (Railway env). Configure in{" "}
        <Link href="/settings" className="text-[var(--accent-teal)] underline">
          Settings
        </Link>
        , then activate each researcher explicitly.
      </Card>

      {loading ? (
        <Skeleton className="h-40 w-full" />
      ) : !arena ? (
        <EmptyState title="Arena unavailable" description="Check login and API health." />
      ) : (
        <>
          <section className="grid gap-3 sm:grid-cols-2">
            {arena.researchers.map((r) => (
              <Card key={r.id} className="panel space-y-2">
                <div className="flex items-start justify-between gap-2">
                  <ResearcherLink slug={r.provider_slug} name={r.display_name} />
                  <span className="text-xs text-zinc-500">{r.connection_status}</span>
                </div>
                <p className="text-xs text-zinc-500">Model {r.model_id || "—"}</p>
                <p className="text-sm text-zinc-300">{r.current_activity || "Idle"}</p>
                <p className="text-xs text-zinc-500">
                  Validated {r.experiments_by_status?.validated ?? 0} · Rejected{" "}
                  {(r.experiments_by_status?.rejected ?? 0) + (r.experiments_by_status?.duplicate ?? 0)}
                </p>
                <p className="text-xs text-zinc-500">
                  Spend ${r.daily_spend_usd.toFixed(3)} today · ${r.monthly_spend_usd.toFixed(2)} month
                </p>
                <button
                  type="button"
                  className="rounded-md border border-zinc-700 px-3 py-1.5 text-xs text-zinc-200 hover:bg-zinc-800"
                  onClick={() => triggerCycle(r.provider_slug)}
                  disabled={!r.activated_by_user}
                >
                  Run cycle
                </button>
                {!r.activated_by_user ? (
                  <p className="text-xs text-amber-200/80">Not activated — enable in Settings after key is set.</p>
                ) : null}
              </Card>
            ))}
          </section>

          <Card className="panel">
            <h2 className="mb-3 text-sm font-semibold text-zinc-200">Validated leaderboard (backtest evidence)</h2>
            <ul className="space-y-2 text-sm">
              {arena.leaderboard.length === 0 ? (
                <li className="text-zinc-500">No validated strategies yet.</li>
              ) : (
                arena.leaderboard.map((row, i) => (
                  <li key={i} className="flex justify-between text-zinc-300">
                    <span>
                      {row.provider_slug} · {row.family} · {row.trade_count} trades
                    </span>
                    <span className="font-mono text-zinc-400">${Number(row.net_pnl).toFixed(0)}</span>
                  </li>
                ))
              )}
            </ul>
          </Card>
        </>
      )}
    </div>
  );
}

function ResearcherLink({ slug, name }: { slug: string; name: string }) {
  return (
    <Link href={`/ai-arena/${slug}`} className="text-base font-medium text-zinc-100 hover:underline">
      {name}
    </Link>
  );
}