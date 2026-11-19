export function PnlText({ value, className = "" }: { value: number; className?: string }) {
  const color = value > 0 ? "text-[var(--profit)]" : value < 0 ? "text-[var(--loss)]" : "text-zinc-300";
  const prefix = value > 0 ? "+$" : value < 0 ? "-$" : "$";
  return (
    <span className={`tabular-nums font-semibold ${color} ${className}`}>
      {prefix}
      {Math.abs(value).toFixed(2)}
    </span>
  );
}