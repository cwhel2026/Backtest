"use client";

import { useEffect, useState } from "react";
import { apiFetch } from "@/lib/api";

type Job = {
  id: string;
  kind: string;
  status: string;
  title: string;
  message: string;
  progress_pct: number;
  created_at: string;
};

export default function ResearchPage() {
  const [jobs, setJobs] = useState<Job[]>([]);

  useEffect(() => {
    const load = () => apiFetch<Job[]>("/api/v1/research/jobs?limit=50").then(setJobs);
    load();
    const t = setInterval(load, 5000);
    return () => clearInterval(t);
  }, []);

  return (
    <div>
      <h2 className="text-2xl font-semibold text-white">Live research monitor</h2>
      <p className="mt-1 text-sm text-zinc-500">Background jobs from Celery workers (refreshes every 5s).</p>
      <div className="mt-6 space-y-3">
        {jobs.length === 0 ? (
          <p className="text-zinc-500">No jobs in queue.</p>
        ) : (
          jobs.map((j) => (
            <div key={j.id} className="rounded-lg border border-zinc-800 bg-[#181b22] p-4">
              <div className="flex items-center justify-between gap-4">
                <p className="font-medium text-zinc-100">{j.title}</p>
                <span className="text-xs text-zinc-400">
                  {j.status} · {j.kind}
                </span>
              </div>
              <p className="mt-2 text-sm text-zinc-500">{j.message}</p>
              <ProgressBar pct={j.progress_pct} />
            </div>
          ))
        )}
      </div>
    </div>
  );
}

function ProgressBar({ pct }: { pct: number }) {
  return (
    <div className="mt-3 h-1.5 w-full overflow-hidden rounded bg-zinc-800">
      <div className="h-full bg-emerald-500 transition-all" style={{ width: `${pct}%` }} />
    </div>
  );
}