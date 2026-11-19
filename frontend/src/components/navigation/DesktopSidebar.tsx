"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { DESKTOP_NAV, isNavActive } from "@/lib/navigation";

export function DesktopSidebar() {
  const pathname = usePathname() || "/";

  return (
    <aside className="hidden w-56 shrink-0 flex-col border-r border-[var(--border)] bg-[var(--shell-nav)] md:flex">
      <div className="border-b border-[var(--border)] px-4 py-5">
        <p className="text-xs font-semibold uppercase tracking-[0.2em] text-zinc-500">Prop Edge</p>
        <h1 className="mt-1 text-lg font-bold text-zinc-100">Research</h1>
      </div>
      <nav className="flex-1 overflow-y-auto p-3">
        <ul className="space-y-0.5">
          {DESKTOP_NAV.map((item) => {
            const active = isNavActive(pathname, item.href);
            return (
              <li key={item.href}>
                <Link
                  href={item.href}
                  className={`flex min-h-[40px] items-center rounded-xl px-3 text-sm ${
                    active
                      ? "bg-[var(--accent-muted)] font-semibold text-[var(--accent)]"
                      : "text-zinc-400 hover:bg-white/5 hover:text-zinc-200"
                  }`}
                >
                  {item.label}
                </Link>
              </li>
            );
          })}
        </ul>
      </nav>
    </aside>
  );
}