"use client";

export function SegmentedControl<T extends string>({
  options,
  value,
  onChange,
}: {
  options: { value: T; label: string }[];
  value: T;
  onChange: (v: T) => void;
}) {
  return (
    <div className="flex gap-1 rounded-xl border border-[var(--border)] bg-[var(--card-elevated)] p-1" role="tablist">
      {options.map((o) => (
        <button
          key={o.value}
          type="button"
          role="tab"
          aria-selected={value === o.value}
          onClick={() => onChange(o.value)}
          className={`min-h-[40px] flex-1 rounded-lg px-2 text-xs font-semibold sm:text-sm ${
            value === o.value ? "bg-[var(--accent-muted)] text-[var(--accent)]" : "text-zinc-500"
          }`}
        >
          {o.label}
        </button>
      ))}
    </div>
  );
}