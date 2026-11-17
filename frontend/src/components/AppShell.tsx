"use client";

import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { setStoredToken } from "@/lib/api";

const NAV = [
  { href: "/", label: "Overview" },
  { href: "/strategies", label: "Strategy Explorer" },
  { href: "/market-data", label: "Market Data" },
  { href: "/research", label: "Live Research" },
  { href: "/paper", label: "Paper Trading" },
  { href: "/prop-firms", label: "Prop-Firm Centre" },
  { href: "/settings", label: "Settings" },
];

export function AppShell({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();
  const router = useRouter();

  function logout() {
    setStoredToken(null);
    router.push("/login");
  }

  return (
    <div className="flex min-h-screen bg-[#12141a] text-zinc-100">
      <aside className="w-64 shrink-0 border-r border-zinc-800 bg-[#0e1015] p-4">
        <div className="mb-8 px-2">
          <p className="text-xs font-semibold tracking-[0.2em] text-emerald-400">PROP EDGE</p>
          <h1 className="text-lg font-medium text-zinc-50">AI Research Terminal</h1>
        </div>
        <nav className="flex flex-col gap-1">
          {NAV.map((item) => {
            const active = pathname === item.href;
            return (
              <Link
                key={item.href}
                href={item.href}
                className={`rounded-md px-3 py-2 text-sm transition ${
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
        <button
          type="button"
          onClick={logout}
          className="mt-8 w-full rounded-md border border-zinc-700 px-3 py-2 text-sm text-zinc-300 hover:bg-zinc-900"
        >
          Sign out
        </button>
      </aside>
      <main className="flex-1 overflow-auto p-8">{children}</main>
    </div>
  );
}