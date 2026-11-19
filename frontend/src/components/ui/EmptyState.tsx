import Link from "next/link";
import { Button } from "@/components/ui/Button";

export function EmptyState({
  title,
  description,
  actionHref,
  actionLabel,
}: {
  title: string;
  description: string;
  actionHref?: string;
  actionLabel?: string;
}) {
  return (
    <div className="panel rounded-2xl border border-dashed border-[var(--border)] px-4 py-8 text-center">
      <h3 className="text-base font-semibold text-zinc-100">{title}</h3>
      <p className="mx-auto mt-2 max-w-md text-sm leading-relaxed text-zinc-400">{description}</p>
      {actionHref && actionLabel ? (
        <Link href={actionHref} className="mt-4 inline-block">
          <Button>{actionLabel}</Button>
        </Link>
      ) : null}
    </div>
  );
}