"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { Card } from "@/components/ui/Card";
import { apiFetch } from "@/lib/api";

type EngineHealth = {
  database: { async_ok: boolean; sync_ok: boolean; sync_detail: string };
  storage: {
    writable: boolean;
    persistent_ok: boolean;
    resolved_path: string;
    railway_volume_mounted?: boolean;
    s3_mirror_configured: boolean;
    s3_ok: boolean;
    s3_detail?: string;
    recommended_path?: string;
  };
  databento: { configured: boolean };
  datasets: { ready: number; blocked: number };
};

export default function SystemHealthPage() {
  const [health, setHealth] = useState<EngineHealth | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    apiFetch<EngineHealth>("/api/v1/market-data/health")
      .then(setHealth)
      .catch((e) => setError(String(e)));
  }, []);

  return (
    <div className="space-y-6">
      <header>
        <h1 className="page-title">System health</h1>
        <p className="page-sub">Database, parquet store, and ingest configuration.</p>
      </header>

      {error ? <Card className="text-sm text-red-200">{error}</Card> : null}

      {health ? (
        <Card className="space-y-3 text-sm text-zinc-300">
          <HealthRow
            label="Database"
            ok={health.database.async_ok && health.database.sync_ok}
            detail={health.database.sync_detail}
          />
          <HealthRow
            label="Parquet store"
            ok={health.storage.writable && health.storage.persistent_ok}
            detail={health.storage.resolved_path}
          />
          <HealthRow label="Databento key" ok={health.databento.configured} detail={health.databento.configured ? "Set" : "Not configured"} />
          <p>
            Datasets: {health.datasets.ready} ready · {health.datasets.blocked} blocked
          </p>
        </Card>
      ) : (
        <p className="text-zinc-500">Loading…</p>
      )}

      <Link href="/market-data" className="text-sm font-medium text-[var(--accent)]">
        ← Market Data
      </Link>
    </div>
  );
}

function HealthRow({ label, ok, detail }: { label: string; ok: boolean; detail: string }) {
  return (
    <div className="flex flex-col gap-1 border-b border-[var(--border)] pb-3 last:border-0">
      <div className="flex items-center justify-between">
        <span className="font-medium text-zinc-100">{label}</span>
        <span className={ok ? "text-emerald-400" : "text-amber-300"}>{ok ? "OK" : "Check"}</span>
      </div>
      <p className="text-xs text-zinc-500">{detail}</p>
    </div>
  );
}