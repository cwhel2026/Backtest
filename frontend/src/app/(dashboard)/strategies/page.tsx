"use client";

import Link from "next/link";
import { useEffect, useMemo, useState } from "react";
import { Card } from "@/components/ui/Card";
import { Button } from "@/components/ui/Button";
import { apiFetch } from "@/lib/api";
import { FEATURED_STRATEGIES, lifecycleLabel } from "@/lib/strategy-catalog";

type Strategy = {
  id: string;
  name: string;
  symbol: string | null;
  category: string;
  timeframe: string;
  lifecycle: string;
  created_at: string;
};

export default function StrategiesPage() {
  const [rows, setRows] = useState<Strategy[]>([]);
  const [query, setQuery] = useState("");

  useEffect(() => {
    apiFetch<Strategy[]>("/api/v1/strategies").then(setRows).catch(() => setRows([]));
  }, []);

  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase();
    if (!q) return rows;
    return rows.filter(
      (r) =>
        r.name.toLowerCase().includes(q) ||
        (r.symbol ?? "").toLowerCase().includes(q) ||
        r.category.toLowerCase().includes(q),
    );
  }, [rows, query]);

  return (
    <div className="space-y-6">
      <header className="flex flex-col gap-3 sm:flex-row sm:items-end sm:justify-between">
        <div>
          <h1 className="page-title">Strategy Lab</h1>
          <p className="page-sub">Berg TNB, liquidity sweep, anchor BOS, and your saved research definitions.</p>
        </div>
        <Link href="/strategies/new">
          <Button variant="secondary" className="w-full sm:w-auto">
            New strategy
          </Button>
        </Link>
      </header>

      <section className="space-y-3">
        <h2 className="text-sm font-semibold uppercase tracking-wide text-zinc-500">Featured</h2>
        <ul className="space-y-3">
          {FEATURED_STRATEGIES.map((f) => (
            <li key={f.key}>
              <Link href={f.href}>
                <Card>
                  <div className="flex items-start justify-between gap-2">
                    <div>
                      <p className="font-semibold text-zinc-50">{f.name}</p>
                      {f.badge ? (
                        <span className="mt-1 inline-block rounded-full bg-[var(--accent-muted)] px-2 py-0.5 text-[10px] font-medium text-[var(--accent)]">
                          {f.badge}
                        </span>
                      ) : null}
                    </div>
                  </div>
                  <p className="mt-2 text-sm text-zinc-400">{f.summary}</p>
                  <p className="mt-2 text-xs text-zinc-500">
                    {f.markets.join(" · ")} — {f.timeframes.join(", ")}
                  </p>
                </Card>
              </Link>
            </li>
          ))}
        </ul>
      </section>

      <section className="space-y-3">
        <h2 className="text-sm font-semibold uppercase tracking-wide text-zinc-500">Library</h2>
        <input
          type="search"
          placeholder="Search strategies…"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          className="w-full rounded-xl border border-[var(--border)] bg-[var(--card-elevated)] px-4 py-3 text-sm"
        />
        <ul className="space-y-2">
          {filtered.length === 0 ? (
            <p className="text-sm text-zinc-500">No strategies match.</p>
          ) : (
            filtered.map((r) => (
              <li key={r.id}>
                <Link href={`/strategies/${r.id}`}>
                  <Card className="py-3">
                    <div className="flex items-center justify-between gap-2">
                      <p className="font-medium text-zinc-100">{r.name}</p>
                      <span className="text-xs text-zinc-500">{lifecycleLabel(r.lifecycle)}</span>
                    </div>
                    <p className="mt-1 text-xs text-zinc-500">
                      {r.symbol ?? "Any"} · {r.timeframe} · {r.category}
                    </p>
                    <span className="mt-2 inline-block text-sm font-medium text-[var(--accent)]">View strategy →</span>
                  </Card>
                </Link>
              </li>
            ))
          )}
        </ul>
      </section>
    </div>
  );
}