import { ReactNode } from "react";

export function Card({
  children,
  className = "",
  onClick,
}: {
  children: ReactNode;
  className?: string;
  onClick?: () => void;
}) {
  const Tag = onClick ? "button" : "div";
  return (
    <Tag
      type={onClick ? "button" : undefined}
      onClick={onClick}
      className={`w-full rounded-2xl border border-[var(--border)] bg-[var(--card)] p-4 text-left shadow-sm ${onClick ? "active:scale-[0.99] transition-transform" : ""} ${className}`}
    >
      {children}
    </Tag>
  );
}