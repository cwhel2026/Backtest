import { ButtonHTMLAttributes, ReactNode } from "react";

type Variant = "primary" | "secondary" | "ghost" | "danger";

const styles: Record<Variant, string> = {
  primary: "bg-[var(--accent)] text-[#041018] hover:brightness-110",
  secondary: "border border-[var(--border)] bg-[var(--card-elevated)] text-zinc-100",
  ghost: "text-zinc-300 hover:bg-white/5",
  danger: "bg-red-900/40 text-red-100 border border-red-800/50",
};

export function Button({
  children,
  variant = "primary",
  className = "",
  fullWidth,
  ...props
}: ButtonHTMLAttributes<HTMLButtonElement> & {
  children: ReactNode;
  variant?: Variant;
  fullWidth?: boolean;
}) {
  return (
    <button
      type="button"
      className={`min-h-[44px] rounded-xl px-4 py-3 text-sm font-semibold disabled:opacity-50 ${styles[variant]} ${fullWidth ? "w-full" : ""} ${className}`}
      {...props}
    >
      {children}
    </button>
  );
}