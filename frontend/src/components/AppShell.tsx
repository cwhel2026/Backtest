"use client";

import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { setStoredToken } from "@/lib/api";

const NAV = [
  { href: "/", label: "Overview", short: "Home" },
  { href: "/strategies", label: "Strategy Explorer", short: "Strategies" },
  { href: "/backtests", label: "Backtest Laboratory", short: "Backtests" },
  { href: "/market-data", label: "Market Data", short: "Data" },
  { href: "/research", label: "Live Research", short: "Research" },
  { href: "/paper", label: "Paper Trading", short: "Paper" },
  { href: "/prop-firms", label: "Prop-Firm Centre", short: "Prop" },
  { href: "/settings", label: "Settings", short: "Settings" },
];

const MOBILE_TABS = NAV.slice(0, 4);

function isNavActive(pathname: string, href: string): boolean {
  if (href === "/") return pathname === "/";
  return pathname === href || pathname.startsWith(`${href}/`);
}

function NavLinks({
  pathname,
  onNavigate,
  className = "",
}: {
  pathname: string;
  onNavigate?: () => void;
  className?: string;
}) {
  return (
    <nav className={`flex flex-col gap-1 ${className}`}>
      {NAV.map((item) => {
        const active = isNavActive(pathname, item.href);
        return (
          <Link
            key={item.href}
            href={item.href}
            onClick={onNavigate}
            className={`rounded-lg px-3 py-3 text-sm transition md:py-2 ${
              active
                ? "bg-zinc-800/80 text-white"
                : "text-zinc-400 hover:bg-zinc-900 hover:text-zinc-100"
            }`}
          >
            {item.label}
          </Link>
        );
      })}
    </nav>
  );
}

export function AppShell({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();
  const router = useRouter();
  const [menuOpen, setMenuOpen] = useState(false);

  useEffect(() => {
    setMenuOpen(false);
  }, [pathname]);

  useEffect(() => {
    if (menuOpen) {
      document.body.style.overflow = "hidden";
    } else {
      document.body.style.overflow = "";
    }
    return () => {
      document.body.style.overflow = "";
    };
  }, [menuOpen]);

  function logout() {
    setStoredToken(null);
    router.push("/login");
  }

  return (
    <div className="flex min-h-screen flex-col bg-[#12141a] text-zinc-100 md:flex-row">
      {/* Mobile header */}
      <header className="sticky top-0 z-40 flex items-center justify-between border-b border-zinc-800 bg-[#0e1015] px-4 py-3 md:hidden">
        <div>
          <p className="text-[10px] font-semibold tracking-[0.2em] text-emerald-400">PROP EDGE</p>
          <p className="text-sm font-medium text-zinc-50">Research</p>
        </div>
        <button
          type="button"
          aria-label={menuOpen ? "Close menu" : "Open menu"}
          onClick={() => setMenuOpen((o) => !o)}
          className="rounded-lg border border-zinc-700 px-3 py-2 text-sm text-zinc-200"
        >
          {menuOpen ? "Close" : "Menu"}
        </button>
      </header>

      {/* Mobile drawer */}
      {menuOpen ? (
        <div className="fixed inset-0 z-50 flex md:hidden">
          <button
            type="button"
            aria-label="Close menu overlay"
            className="absolute inset-0 bg-black/60"
            onClick={() => setMenuOpen(false)}
          />
          <aside className="relative ml-auto flex h-full w-[min(100%,280px)] flex-col border-l border-zinc-800 bg-[#0e1015] p-4 shadow-xl">
            <NavLinks pathname={pathname} onNavigate={() => setMenuOpen(false)} className="flex-1 overflow-y-auto" />
            <button
              type="button"
              onClick={logout}
              className="mt-4 w-full rounded-lg border border-zinc-700 px-3 py-3 text-sm text-zinc-300"
            >
              Sign out
            </button>
          </aside>
        </div>
      ) : null}

      {/* Desktop sidebar */}
      <aside className="hidden w-64 shrink-0 border-r border-zinc-800 bg-[#0e1015] p-4 md:block">
        <div className="mb-8 px-2">
          <p className="text-xs font-semibold tracking-[0.2em] text-emerald-400">PROP EDGE</p>
          <h1 className="text-lg font-medium text-zinc-50">AI Research Terminal</h1>
        </div>
        <NavLinks pathname={pathname} />
        <button
          type="button"
          onClick={logout}
          className="mt-8 w-full rounded-md border border-zinc-700 px-3 py-2 text-sm text-zinc-300 hover:bg-zinc-900"
        >
          Sign out
        </button>
      </aside>

      <div className="flex min-h-0 flex-1 flex-col">
        <main className="flex-1 overflow-x-hidden overflow-y-auto p-4 pb-24 md:p-8 md:pb-8">{children}</main>

        {/* Mobile bottom navigation */}
        <nav
          className="fixed bottom-0 left-0 right-0 z-30 grid grid-cols-4 border-t border-zinc-800 bg-[#0e1015]/95 pb-[env(safe-area-inset-bottom)] backdrop-blur md:hidden"
          aria-label="Primary"
        >
          {MOBILE_TABS.map((item) => {
            const active = isNavActive(pathname, item.href);
            return (
              <Link
                key={item.href}
                href={item.href}
                className={`flex flex-col items-center justify-center px-1 py-2.5 text-[10px] leading-tight ${
                  active ? "text-emerald-400" : "text-zinc-500"
                }`}
              >
                <span className="font-medium">{item.short}</span>
              </Link>
            );
          })}
        </nav>
      </div>
    </div>
  );
}