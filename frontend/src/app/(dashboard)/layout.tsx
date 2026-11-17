"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { AppShell } from "@/components/AppShell";
import { getStoredToken } from "@/lib/api";

export default function DashboardLayout({ children }: { children: React.ReactNode }) {
  const router = useRouter();
  const [ready, setReady] = useState(false);

  useEffect(() => {
    if (!getStoredToken()) router.replace("/login");
    else setReady(true);
  }, [router]);

  if (!ready) {
    return <div className="flex min-h-screen items-center justify-center bg-[#12141a] text-zinc-400">Loading…</div>;
  }

  return <AppShell>{children}</AppShell>;
}