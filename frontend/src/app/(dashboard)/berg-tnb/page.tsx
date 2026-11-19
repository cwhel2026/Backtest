"use client";

import { useEffect, useState } from "react";
import { apiFetch } from "@/lib/api";

type Template = {
  entry: Record<string, unknown>;
  pdf_note: string;
  session_profiles: string[];
};

type Timeline = {
  setups: Array<{ setup_id: string; final_state: string; transitions: Array<Record<string, unknown>> }>;
  order_count: number;
  dataset_version: string | null;
};

export default function BergTnbPage() {
  const [template, setTemplate] = useState<Template | null>(null);
  const [datasetId, setDatasetId] = useState("");
  const [timeline, setTimeline] = useState<Timeline | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    apiFetch<Template>("/api/v1/berg-tnb/spec-template")
      .then(setTemplate)
      .catch((e) => setError(String(e)));
  }, []);

  async function preview() {
    setError(null);
    if (!template || !datasetId.trim()) {
      setError("Enter a validated dataset UUID.");
      return;
    }
    try {
      const spec = {
        name: "Berg preview",
        instrument_symbol: "MES",
        timeframe: "5m",
        entry: template.entry,
        exit: { stop_ticks: 20, target_ticks: 40 },
        exit_meta: { profile: "structural_rr", reward_risk: "2" },
        risk: { dollar_risk_per_trade: 75, max_contracts: 2 },
      };
      const res = await apiFetch<Timeline>("/api/v1/berg-tnb/preview-timeline", {
        method: "POST",
        body: JSON.stringify({
          dataset_id: datasetId.trim(),
          specification: spec,
        }),
      });
      setTimeline(res);
    } catch (e) {
      setError(String(e));
    }
  }

  return (
    <div className="mx-auto max-w-4xl space-y-6 p-6 text-zinc-200">
      <h1 className="text-xl font-semibold">Berg TNB Model v1</h1>
      <p className="text-sm text-zinc-400">
        Research pipeline: 4H bias → session level → sweep → reversal → 0.079 fakeout → 5m BOS → entry fib.
        PDF not in repo — see <code className="text-amber-200/80">docs/BERG_TNB_MODEL.md</code>.
      </p>
      {template && (
        <ul className="list-disc space-y-1 pl-5 text-sm text-zinc-400">
          <li>Fakeout fib (orange): {String(template.entry.fib_fakeout_ratio)}</li>
          <li>Entry fib (blue): {String(template.entry.entry_fib_ratio)}</li>
          <li>Profiles: {template.session_profiles.join(", ")}</li>
        </ul>
      )}
      <div className="flex flex-wrap gap-2">
        <input
          className="min-w-[280px] rounded border border-zinc-700 bg-zinc-900 px-3 py-2 text-sm"
          placeholder="Dataset UUID (5m validated)"
          value={datasetId}
          onChange={(e) => setDatasetId(e.target.value)}
        />
        <button
          type="button"
          onClick={() => void preview()}
          className="rounded bg-amber-600/90 px-4 py-2 text-sm font-medium text-black"
        >
          Preview setup timeline
        </button>
      </div>
      {error && <p className="text-sm text-red-400">{error}</p>}
      {timeline && (
        <section className="space-y-3 rounded-lg border border-zinc-800 bg-zinc-900/50 p-4">
          <h2 className="text-sm font-medium">Timeline ({timeline.setups.length} setups, {timeline.order_count} orders)</h2>
          {timeline.setups.map((s) => (
            <div key={s.setup_id} className="border-t border-zinc-800 pt-3 text-xs">
              <div className="font-mono text-amber-200/90">{s.final_state}</div>
              <ol className="mt-2 space-y-1 text-zinc-500">
                {s.transitions.map((t, i) => (
                  <li key={i}>
                    {String(t.to)} — {String(t.reason)} @ bar {String(t.bar_index)}
                  </li>
                ))}
              </ol>
            </div>
          ))}
        </section>
      )}
    </div>
  );
}