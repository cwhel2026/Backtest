"use client";

import Link from "next/link";
import { MORE_LINKS } from "@/lib/navigation";
import { Card } from "@/components/ui/Card";

export default function MorePage() {
  return (
    <div className="space-y-6">
      <header>
        <h1 className="page-title">More</h1>
        <p className="page-sub">Data, rankings, debugger, and system tools.</p>
      </header>
      <ul className="space-y-2">
        {MORE_LINKS.map((item) => (
          <li key={item.href}>
            <Link href={item.href}>
              <Card className="flex min-h-[52px] items-center justify-between py-3">
                <span className="font-medium text-zinc-100">{item.label}</span>
                <span className="text-zinc-500" aria-hidden>
                  →
                </span>
              </Card>
            </Link>
          </li>
        ))}
      </ul>
    </div>
  );
}