"use client";

import { useParams } from "next/navigation";
import { useEffect, useState } from "react";
import { Card } from "@/components/ui/Card";
import { apiFetch } from "@/lib/api";

type ResearcherDetail = {
  researcher: { display_name: string; current_activity: string; objectives: Record<string, unknown> };
  experiments: { id: string; status: string; family: string; hypothesis: string; metrics: Record<string, unknown> }[];
};

export default function ResearcherPage() {
  const params = useParams();
  const slug = String(params.slug);
  const [data, setData] = useState<ResearcherDetail | null>(null);

  useEffect(() => {
    apiFetch<ResearcherDetail>(`/api/v1/ai-arena/researchers/${slug}`).then(setData).catch(() => setData(null));
  }, [slug]);

  if (!data) return <p className="text-zinc-500">Loading…</p>;

  return (
    <div className="space-y-4 pb-10">
      <h1 className="page-title">{data.researcher.display_name}</h1>
      <p className="text-sm text-zinc-400">{data.researcher.current_activity}</p>
      <Card className="panel space-y-3">
        {data.experiments.map((e) => (
          <div key={e.id} className="border-b border-zinc-800 pb-3 last:border-0">
            <p className="text-sm font-medium text-zinc-200">
              {e.status} · {e.family}
            </p>
            <p className="text-xs text-zinc-500">{e.hypothesis}</p>
            {e.metrics?.net_pnl != null ? (
              <p className="text-xs text-zinc-400">
                Backtest net ${String(e.metrics.net_pnl)} · {String(e.metrics.trade_count)} trades
              </p>
            ) : null}
          </div>
        ))}
      </Card>
    </div>
  );
}