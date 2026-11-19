"use client";

import { useEffect, useMemo, useState } from "react";
import { LeaderboardCard, type LeaderboardEntry } from "@/components/LeaderboardCard";
import { apiFetch } from "@/lib/api";
import { Button } from "@/components/ui/Button";

type SortKey =
  | "net"
  | "pf"
  | "dd"
  | "expectancy"
  | "trades"
  | "holdout"
  | "prop";

const SORT_OPTIONS: { key: SortKey; label: string }[] = [
  { key: "net", label: "Net P&L" },
  { key: "pf", label: "Profit factor" },
  { key: "dd", label: "Max DD" },
  { key: "expectancy", label: "Avg R / expectancy" },
  { key: "trades", label: "Trades" },
  { key: "holdout", label: "Holdout" },
  { key: "prop", label: "Prop score" },
];

function sortRows(rows: LeaderboardEntry[], key: SortKey): LeaderboardEntry[] {
  const copy = [...rows];
  const m = (r: LeaderboardEntry) => r.metrics;
  copy.sort((a, b) => {
    switch (key) {
      case "net":
        return (m(b).net_profit_usd ?? 0) - (m(a).net_profit_usd ?? 0);
      case "pf":
        return (m(b).profit_factor ?? 0) - (m(a).profit_factor ?? 0);
      case "dd":
        return (m(a).max_drawdown_usd ?? 0) - (m(b).max_drawdown_usd ?? 0);
      case "expectancy":
        return (m(b).expectancy_usd ?? 0) - (m(a).expectancy_usd ?? 0);
      case "trades":
        return (m(b).trade_count ?? 0) - (m(a).trade_count ?? 0);
      case "holdout":
        return (m(b).holdout_net_usd ?? 0) - (m(a).holdout_net_usd ?? 0);
      case "prop":
        return (b.prop_ready_score ?? 0) - (a.prop_ready_score ?? 0);
      default:
        return 0;
    }
  });
  return copy;
}

export default function LeaderboardPage() {
  const [rows, setRows] = useState<LeaderboardEntry[]>([]);
  const [sort, setSort] = useState<SortKey>("prop");
  const [genuineOnly, setGenuineOnly] = useState(true);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    setLoading(true);
    apiFetch<LeaderboardEntry[]>(`/api/v1/autopilot/leaderboard?profitable_only=${genuineOnly}&limit=80`)
      .then(setRows)
      .finally(() => setLoading(false));
  }, [genuineOnly]);

  const sorted = useMemo(() => sortRows(rows, sort), [rows, sort]);

  return (
    <div className="space-y-5">
      <header>
        <h1 className="page-title">Leaderboard</h1>
        <p className="page-sub">
          Genuine validated keepers by default. Toggle to include probes and small samples — cards flag weak evidence.
        </p>
      </header>

      <div className="flex flex-wrap gap-2">
        {SORT_OPTIONS.map((o) => (
          <Button
            key={o.key}
            variant={sort === o.key ? "primary" : "secondary"}
            className="min-h-[40px] px-3 py-2 text-xs"
            onClick={() => setSort(o.key)}
          >
            {o.label}
          </Button>
        ))}
      </div>

      <label className="flex min-h-[44px] items-center gap-3 text-sm text-zinc-300">
        <input
          type="checkbox"
          checked={!genuineOnly}
          onChange={(e) => setGenuineOnly(!e.target.checked)}
          className="h-5 w-5 rounded border-zinc-600"
        />
        Include unvalidated / probe feeds
      </label>

      {loading ? (
        <p className="text-zinc-500">Loading…</p>
      ) : sorted.length === 0 ? (
        <p className="text-sm text-zinc-500">No results match this filter.</p>
      ) : (
        <ul className="space-y-4">
          {sorted.map((r) => (
            <LeaderboardCard key={r.run_id} row={r} />
          ))}
        </ul>
      )}
    </div>
  );
}