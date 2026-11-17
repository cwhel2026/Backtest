"use client";

import { useEffect, useState } from "react";
import { apiFetch } from "@/lib/api";

type Activity = { headline: string; detail: string; created_at: string };

export default function PaperTradingPage() {
  const [sims, setSims] = useState<Activity[]>([]);

  useEffect(() => {
    apiFetch<Activity[]>("/api/v1/research/activity?limit=30").then((rows) =>
      setSims(rows.filter((r) => r.headline.toLowerCase().includes("live sim")))
    );
  }, []);

  return (
    <div>
      <h2 className="page-title">Live-style simulation</h2>
      <p className="page-sub max-w-2xl">
        After each autopilot cycle, strategies are replayed on the most recent market bars (Yahoo data). This is
        simulated only — not connected to any prop firm or broker account.
      </p>
      <ul className="mt-6 space-y-3">
        {sims.length === 0 ? (
          <li className="text-sm text-zinc-500">No simulations yet. Run the autopilot from Home.</li>
        ) : (
          sims.map((s, i) => (
            <li key={i} className="rounded-lg border border-zinc-800 bg-[#181b22] p-4 text-sm">
              <p className="font-medium text-zinc-100">{s.headline}</p>
              <p className="mt-1 text-zinc-500">{s.detail}</p>
            </li>
          ))
        )}
      </ul>
    </div>
  );
}