"use client";

import Link from "next/link";
import { Card } from "@/components/ui/Card";
import { ADVANCED_NAV, MENU_NAV, PRIMARY_NAV } from "@/lib/navigation";

export default function MenuPage() {
  const sections = [
    { title: "Trading & analysis", items: MENU_NAV },
    {
      title: "Quick links",
      items: PRIMARY_NAV.filter((p) => !MENU_NAV.find((m) => m.href === p.href) && p.href !== "/"),
    },
    { title: "Advanced tools", items: ADVANCED_NAV },
  ];

  return (
    <div className="space-y-6 pb-24">
      <header>
        <h1 className="page-title">Menu</h1>
        <p className="page-sub">Paper trading, analytics, research, settings, and power-user tools.</p>
      </header>
      {sections.map((sec) => (
        <section key={sec.title} className="space-y-2">
          <h2 className="text-xs font-semibold uppercase tracking-wider text-zinc-500">{sec.title}</h2>
          <ul className="space-y-2">
            {sec.items.map((item) => (
              <li key={item.href}>
                <Link href={item.href}>
                  <Card className="flex min-h-[52px] items-center justify-between py-3">
                    <span className="font-medium text-zinc-100">{item.label}</span>
                    <span className="text-zinc-500">→</span>
                  </Card>
                </Link>
              </li>
            ))}
          </ul>
        </section>
      ))}
    </div>
  );
}