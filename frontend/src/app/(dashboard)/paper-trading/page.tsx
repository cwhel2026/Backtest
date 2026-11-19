"use client";

import { PaperTradingDashboard } from "@/components/paper/PaperTradingDashboard";

export default function PaperTradingPage() {
  return (
    <div className="space-y-4 pb-8">
      <header>
        <h1 className="page-title">Paper Trading</h1>
        <p className="page-sub">
          Simulated forward execution on your configured data feed. Orders stay on the research ledger — never live
          capital.
        </p>
      </header>
      <PaperTradingDashboard />
    </div>
  );
}