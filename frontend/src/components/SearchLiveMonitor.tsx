"use client";

const PHASE_LABELS: Record<string, string> = {
  queued: "Waiting for worker",
  starting: "Starting",
  loading_data: "Downloading Yahoo 5m bars",
  scoring: "Walk-forward scoring",
  saving: "Saving keepers",
  completed: "Finished",
  failed: "Failed",
};

const SUBPHASE_LABELS: Record<string, string> = {
  start: "Beginning symbol",
  sample: "Picking combo",
  train: "Train window",
  oos: "Out-of-sample",
  prop_screen: "Prop screen (full sample)",
  reverse_train: "Reverse · train",
  reverse_oos: "Reverse · OOS",
  reverse_full: "Reverse · full",
  refine_train: "Refine · train",
  refine_oos: "Refine · OOS",
  refine_full: "Refine · full",
  persist: "Writing backtests",
};

type Live = {
  phase?: string | null;
  symbols?: string[];
  symbol_index?: number;
  current_symbol?: string | null;
  combos_per_symbol?: number;
  combos_completed?: number;
  history_days?: number;
  tests_completed?: number;
  tests_target_estimate?: number;
  current_setup?: string | null;
  setup_family?: string | null;
  scoring_subphase?: string | null;
  search_families?: string[];
  walk_forward?: string | null;
  markets_loaded?: string[];
  winners_saved?: number;
  symbols_finished?: string[];
  heartbeat_at?: string | null;
};

type SearchPlan = {
  symbols: string[];
  combos_per_symbol: number;
  history_days: number;
  families: string[];
  walk_forward: string;
  reverse_fades: boolean;
};

type JobLogLine = { headline: string; detail: string; created_at: string };

type Props = {
  status: string;
  message: string;
  progressPct: number;
  live: Live | null | undefined;
  plan: SearchPlan | null | undefined;
  jobLog: JobLogLine[];
  active: boolean;
};

function phaseLabel(phase: string | null | undefined): string {
  if (!phase) return "—";
  return PHASE_LABELS[phase] ?? phase.replace(/_/g, " ");
}

function secondsSince(iso: string | null | undefined): number | null {
  if (!iso) return null;
  const t = Date.parse(iso);
  if (Number.isNaN(t)) return null;
  return Math.max(0, Math.floor((Date.now() - t) / 1000));
}

export function SearchLiveMonitor({ status, message, progressPct, live, plan, jobLog, active }: Props) {
  const symbols = live?.symbols?.length ? live.symbols : plan?.symbols ?? [];
  const families = live?.search_families?.length ? live.search_families : plan?.families ?? [];
  const combos = live?.combos_per_symbol ?? plan?.combos_per_symbol ?? 0;
  const history = live?.history_days ?? plan?.history_days ?? 0;
  const subphase = live?.scoring_subphase ? SUBPHASE_LABELS[live.scoring_subphase] ?? live.scoring_subphase : null;
  const heartbeatAge = secondsSince(live?.heartbeat_at ?? null);
  const combosDone = live?.combos_completed ?? 0;
  const stallWarning =
    active &&
    heartbeatAge != null &&
    heartbeatAge > 75 &&
    (live?.phase === "scoring" || live?.phase === "loading_data");

  return (
    <section className="rounded-xl border border-amber-900/40 bg-[#151820] p-4 md:p-5">
      <div className="flex flex-col gap-2 md:flex-row md:items-center md:justify-between">
        <div>
          <h3 className="text-sm font-semibold text-amber-100">Live search monitor</h3>
          <p className="mt-0.5 text-xs text-zinc-500">
            {active
              ? "Updates every few seconds while the worker scores on the server."
              : "How each prop search run works (same engine when you press Run)."}
          </p>
        </div>
        <span className="text-xs font-medium uppercase tracking-wide text-amber-200/80">{status}</span>
      </div>

      <div className="mt-4 h-2 overflow-hidden rounded-full bg-zinc-800">
        <div
          className={`h-full rounded-full bg-gradient-to-r from-amber-600 to-emerald-500 transition-all duration-500 ${
            active ? "animate-pulse" : ""
          }`}
          style={{ width: `${Math.min(100, Math.max(active ? 3 : 0, progressPct))}%` }}
        />
      </div>
      <p className="mt-2 text-sm text-zinc-200">{message}</p>
      {active && heartbeatAge != null ? (
        <p className="mt-1 text-xs text-zinc-500">
          Server heartbeat {heartbeatAge}s ago
          {combos > 0 ? ` · combo ${combosDone} / ${combos} on this market` : ""}
        </p>
      ) : null}
      {stallWarning ? (
        <p className="mt-2 text-xs text-amber-200">
          Still crunching one heavy backtest (up to ~90s per combo). The counter may pause briefly — if this
          line is over 3 minutes old, press Restart search.
        </p>
      ) : null}

      <dl className="mt-4 grid gap-3 text-xs md:grid-cols-2">
        <div className="rounded-lg border border-zinc-800 bg-zinc-900/40 p-3">
          <dt className="font-medium text-zinc-400">Phase</dt>
          <dd className="mt-1 text-sm text-zinc-100">{phaseLabel(live?.phase)}</dd>
          {subphase ? <dd className="mt-1 text-amber-200/90">Step: {subphase}</dd> : null}
        </div>
        <div className="rounded-lg border border-zinc-800 bg-zinc-900/40 p-3">
          <dt className="font-medium text-zinc-400">Markets (round-robin)</dt>
          <dd className="mt-1 flex flex-wrap gap-1">
            {symbols.map((sym) => {
              const done = live?.symbols_finished?.includes(sym);
              const current = live?.current_symbol === sym && live?.phase === "scoring";
              return (
                <span
                  key={sym}
                  className={`rounded px-1.5 py-0.5 ${
                    current
                      ? "bg-amber-950 text-amber-200 ring-1 ring-amber-700"
                      : done
                        ? "bg-emerald-950/50 text-emerald-300"
                        : "bg-zinc-800 text-zinc-400"
                  }`}
                >
                  {sym}
                </span>
              );
            })}
          </dd>
        </div>
        <div className="rounded-lg border border-zinc-800 bg-zinc-900/40 p-3 md:col-span-2">
          <dt className="font-medium text-zinc-400">What we try per market</dt>
          <dd className="mt-1 text-sm text-zinc-200">
            <span className="font-mono text-amber-200/90">{combos}</span> stratified combos · Yahoo{" "}
            <span className="font-mono">{history}</span>d · 5m · {live?.walk_forward ?? plan?.walk_forward}
            {plan?.reverse_fades ? " · low-WR reverse fades" : ""}
          </dd>
          <dd className="mt-2 flex flex-wrap gap-1">
            {families.map((f) => (
              <span
                key={f}
                className={`rounded border px-2 py-0.5 ${
                  live?.setup_family === f || live?.setup_family?.includes(f)
                    ? "border-amber-700 bg-amber-950/40 text-amber-100"
                    : "border-zinc-700 text-zinc-500"
                }`}
              >
                {f}
              </span>
            ))}
          </dd>
        </div>
        {live?.current_setup ? (
          <div className="rounded-lg border border-zinc-800 bg-zinc-900/40 p-3 md:col-span-2">
            <dt className="font-medium text-zinc-400">Scoring now</dt>
            <dd className="mt-1 font-mono text-sm text-emerald-200/95">{live.current_setup}</dd>
            {live.tests_completed != null && live.tests_completed > 0 ? (
              <dd className="mt-1 text-zinc-500">
                {live.tests_completed.toLocaleString()} backtest runs
                {live.tests_target_estimate
                  ? ` (est. up to ${live.tests_target_estimate.toLocaleString()} for this symbol)`
                  : ""}
              </dd>
            ) : null}
          </div>
        ) : null}
        {live?.markets_loaded?.length ? (
          <div className="rounded-lg border border-zinc-800 bg-zinc-900/40 p-3 md:col-span-2">
            <dt className="font-medium text-zinc-400">Data loaded</dt>
            <dd className="mt-1 text-zinc-300">{live.markets_loaded.join(" · ")}</dd>
          </div>
        ) : null}
      </dl>

      {jobLog.length > 0 ? (
        <div className="mt-4">
          <p className="text-xs font-medium text-zinc-400">This run</p>
          <ul className="mt-2 max-h-40 space-y-2 overflow-y-auto text-xs">
            {jobLog.map((line, i) => (
              <li key={`${line.created_at}-${i}`} className="border-l-2 border-zinc-700 pl-2">
                <p className="text-zinc-200">{line.headline}</p>
                {line.detail ? <p className="text-zinc-500">{line.detail}</p> : null}
              </li>
            ))}
          </ul>
        </div>
      ) : null}
    </section>
  );
}