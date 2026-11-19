"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { isNavActive, MOBILE_PRIMARY } from "@/lib/navigation";

export function MobileTabBar() {
  const pathname = usePathname() || "/";

  return (
    <nav
      className="fixed bottom-0 left-0 right-0 z-50 border-t border-[var(--border)] bg-[var(--shell-nav)] pb-[env(safe-area-inset-bottom,0px)] md:hidden"
      aria-label="Primary"
    >
      <ul className="mx-auto flex max-w-lg items-stretch justify-around px-1 pt-1">
        {MOBILE_PRIMARY.map((item) => {
          const active =
            item.href === "/more"
              ? pathname === "/more" || ["/market-data", "/leaderboard", "/settings"].some((p) => pathname.startsWith(p))
              : isNavActive(pathname, item.href);
          return (
            <li key={item.href} className="flex-1">
              <Link
                href={item.href}
                className={`flex min-h-[52px] flex-col items-center justify-center gap-0.5 rounded-xl px-1 text-[10px] font-medium tracking-wide ${
                  active ? "text-[var(--accent)]" : "text-zinc-500"
                }`}
              >
                <span className="text-lg leading-none" aria-hidden>
                  {item.icon}
                </span>
                <span>{item.short}</span>
              </Link>
            </li>
          );
        })}
      </ul>
    </nav>
  );
}