"use client";

import { usePathname, useRouter } from "next/navigation";
import { setStoredToken } from "@/lib/api";
import { DesktopSidebar } from "@/components/navigation/DesktopSidebar";
import { MobileTabBar } from "@/components/navigation/MobileTabBar";
import { Button } from "@/components/ui/Button";

export function AppShell({ children }: { children: React.ReactNode }) {
  const router = useRouter();
  const pathname = usePathname();

  function logout() {
    setStoredToken(null);
    router.push("/login");
  }

  return (
    <div className="flex min-h-[100dvh] flex-col bg-[var(--background)] text-zinc-100 md:flex-row">
      {/* Mobile header */}
      <header className="sticky top-0 z-40 flex items-center justify-between border-b border-[var(--border)] bg-[var(--shell-nav)] px-4 py-3 pt-[max(12px,env(safe-area-inset-top))] md:hidden">
        <div>
          <p className="text-[10px] font-semibold tracking-[0.25em] text-[var(--accent)]">PROP EDGE AI</p>
          <p className="text-sm font-semibold text-zinc-50">Research</p>
        </div>
        <Button variant="ghost" className="min-h-[40px] px-3 py-2 text-xs" onClick={logout}>
          Sign out
        </Button>
      </header>

      <DesktopSidebar />

      <div className="flex min-h-0 min-w-0 flex-1 flex-col">
        {/* Desktop top bar */}
        <header className="hidden items-center justify-between border-b border-[var(--border)] bg-[var(--shell-nav)] px-8 py-4 md:flex">
          <p className="text-sm text-zinc-500">
            <span className="text-zinc-300">Terminal</span>
            {pathname && pathname !== "/" ? ` · ${pathname.split("/").filter(Boolean).join(" / ")}` : ""}
          </p>
          <Button variant="secondary" className="min-h-[36px] py-2 text-xs" onClick={logout}>
            Sign out
          </Button>
        </header>

        <main className="mx-auto w-full max-w-3xl flex-1 overflow-x-hidden overflow-y-auto px-4 py-5 pb-[calc(88px+env(safe-area-inset-bottom,0px))] md:max-w-6xl md:px-8 md:py-8 md:pb-8">
          {children}
        </main>

        <MobileTabBar />
      </div>
    </div>
  );
}