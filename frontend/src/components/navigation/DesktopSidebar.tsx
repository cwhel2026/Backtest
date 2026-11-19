"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useState } from "react";
import { ADVANCED_NAV, DESKTOP_NAV, isNavActive } from "@/lib/navigation";

export function DesktopSidebar() {
  const pathname = usePathname() || "/";
  const [collapsed, setCollapsed] = useState(false);
  const [advancedOpen, setAdvancedOpen] = useState(false);

  return (
    <aside
      className={`hidden shrink-0 flex-col border-r border-[var(--border)] bg-[var(--shell-nav)] transition-all md:flex ${
        collapsed ? "w-[72px]" : "w-60"
      }`}
    >
      <div className="flex items-center justify-between border-b border-[var(--border)] px-3 py-4">
        {!collapsed ? (
          <div>
            <p className="text-[10px] font-semibold tracking-[0.22em] text-[var(--accent-teal)]">PROP EDGE AI</p>
            <h1 className="mt-0.5 text-sm font-bold text-zinc-100">Research Terminal</h1>
          </div>
        ) : (
          <span className="mx-auto text-lg text-[var(--accent)]" aria-hidden>
            ◆
          </span>
        )}
        <button
          type="button"
          onClick={() => setCollapsed((c) => !c)}
          className="touch-target rounded-lg px-2 text-xs text-zinc-500 hover:bg-white/5"
          aria-label={collapsed ? "Expand sidebar" : "Collapse sidebar"}
        >
          {collapsed ? "»" : "«"}
        </button>
      </div>
      <nav className="flex-1 overflow-y-auto p-2">
        <ul className="space-y-0.5">
          {DESKTOP_NAV.map((item) => {
            const active = isNavActive(pathname, item.href);
            return (
              <li key={item.href}>
                <Link
                  href={item.href}
                  title={item.label}
                  className={`flex min-h-[42px] items-center gap-3 rounded-xl px-3 text-sm ${
                    active
                      ? "bg-[var(--accent-muted)] font-semibold text-[var(--accent)]"
                      : "text-zinc-400 hover:bg-white/5 hover:text-zinc-200"
                  }`}
                >
                  <span className="w-5 text-center text-base" aria-hidden>
                    {item.icon}
                  </span>
                  {!collapsed ? <span>{item.label}</span> : null}
                </Link>
              </li>
            );
          })}
        </ul>
        {!collapsed ? (
          <div className="mt-6 border-t border-[var(--border)] pt-4">
            <button
              type="button"
              onClick={() => setAdvancedOpen((o) => !o)}
              className="mb-2 w-full px-3 text-left text-[10px] font-semibold uppercase tracking-wider text-zinc-500"
            >
              Advanced {advancedOpen ? "▾" : "▸"}
            </button>
            {advancedOpen ? (
              <ul className="space-y-0.5">
                {ADVANCED_NAV.map((item) => (
                  <li key={item.href}>
                    <Link
                      href={item.href}
                      className="block rounded-lg px-3 py-2 text-xs text-zinc-500 hover:bg-white/5 hover:text-zinc-300"
                    >
                      {item.label}
                    </Link>
                  </li>
                ))}
              </ul>
            ) : null}
          </div>
        ) : null}
      </nav>
    </aside>
  );
}