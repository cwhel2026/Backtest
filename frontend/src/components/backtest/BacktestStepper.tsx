"use client";

const STEPS = ["Strategy", "Market", "Dataset", "Risk", "Run"] as const;

export function BacktestStepper({ step }: { step: number }) {
  return (
    <ol className="flex gap-1" aria-label="Backtest progress">
      {STEPS.map((label, i) => {
        const active = i === step;
        const done = i < step;
        return (
          <li key={label} className="flex-1">
            <div
              className={`h-1.5 rounded-full ${done ? "bg-[var(--accent)]" : active ? "bg-[var(--accent)]/60" : "bg-zinc-800"}`}
            />
            <p className={`mt-1 text-[10px] ${active ? "text-[var(--accent)]" : "text-zinc-600"}`}>{label}</p>
          </li>
        );
      })}
    </ol>
  );
}