"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { Card } from "@/components/ui/Card";
import { Button } from "@/components/ui/Button";
import { apiFetch } from "@/lib/api";
import { ADVANCED_NAV } from "@/lib/navigation";

type Health = {
  database: { async_ok: boolean; sync_ok: boolean };
  storage?: { writable?: boolean; persistent_ok?: boolean };
};

type AiProvider = { slug: string; env_var: string; key_configured: boolean; default_model: string; docs_url: string };

export default function SettingsPage() {
  const [health, setHealth] = useState<Health | null>(null);
  const [aiProviders, setAiProviders] = useState<AiProvider[]>([]);

  useEffect(() => {
    apiFetch<Health>("/api/v1/market-data/health").then(setHealth).catch(() => setHealth(null));
    apiFetch<{ providers: AiProvider[] }>("/api/v1/ai-arena/providers")
      .then((r) => setAiProviders(r.providers))
      .catch(() => setAiProviders([]));
  }, []);

  const sections = [
    {
      title: "Market data",
      body: "Import licensed history, estimate Databento bundles, and check dataset readiness.",
      href: "/market-data",
      cta: "Historical data",
    },
    {
      title: "Paper trading policy",
      body: "Forward simulation uses the Live Strategy Lab worker. Certification status is in Accuracy Certification.",
      href: "/paper-trading/certification",
      cta: "Certification",
    },
    {
      title: "System health",
      body: health
        ? `Database ${health.database?.sync_ok ? "OK" : "check"} · store ${health.storage?.writable ? "writable" : "verify volume"}`
        : "Could not load health endpoint.",
      href: "/market-data/health",
      cta: "Health panel",
    },
  ];

  return (
    <div className="max-w-2xl space-y-6 pb-8">
      <header>
        <h1 className="page-title">Settings</h1>
        <p className="page-sub">Data providers, execution assumptions, and worker health. API keys stay on the server only.</p>
      </header>

      <ul className="space-y-3">
        {sections.map((s) => (
          <li key={s.title}>
            <Card className="panel space-y-2">
              <h2 className="font-semibold text-zinc-100">{s.title}</h2>
              <p className="text-sm text-zinc-400">{s.body}</p>
              <Link href={s.href}>
                <Button variant="secondary">{s.cta}</Button>
              </Link>
            </Card>
          </li>
        ))}
      </ul>

      <section>
        <h2 className="mb-2 text-sm font-semibold text-zinc-200">AI Research Arena</h2>
        <Card className="panel space-y-2 text-sm text-zinc-400">
          <p>
            Keys are set only in Railway/environment (<code className="text-zinc-300">OPENAI_API_KEY</code>,{" "}
            <code className="text-zinc-300">ANTHROPIC_API_KEY</code>, etc.). This UI never stores secrets.
          </p>
          <ul className="space-y-1">
            {aiProviders.map((p) => (
              <li key={p.slug}>
                <span className="text-zinc-200">{p.slug}</span> · env <code>{p.env_var}</code> ·{" "}
                {p.key_configured ? "key present" : "not configured"} · model {p.default_model}
              </li>
            ))}
          </ul>
          <Link href="/ai-arena" className="text-[var(--accent-teal)] hover:underline">
            Open AI Arena to activate researchers
          </Link>
        </Card>
      </section>

      <section>
        <h2 className="mb-2 text-sm font-semibold text-zinc-200">Backtest assumptions</h2>
        <Card className="panel text-sm text-zinc-400">
          Slippage and commissions are set per backtest run and in strategy definitions. Use the Backtesting wizard step
          “Execution assumptions” to adjust friction; defaults are not hidden in environment variables on this screen.
        </Card>
      </section>

      <section>
        <h2 className="mb-2 text-sm font-semibold text-zinc-200">Advanced</h2>
        <ul className="space-y-1 text-sm">
          {ADVANCED_NAV.map((item) => (
            <li key={item.href}>
              <Link href={item.href} className="text-[var(--accent)] hover:underline">
                {item.label}
              </Link>
            </li>
          ))}
        </ul>
      </section>
    </div>
  );
}