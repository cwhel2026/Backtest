"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { ScrollTable } from "@/components/ScrollTable";
import { apiFetch } from "@/lib/api";

type Strategy = {
  id: string;
  name: string;
  symbol: string | null;
  category: string;
  timeframe: string;
  lifecycle: string;
  created_at: string;
};

export default function StrategiesPage() {
  const [rows, setRows] = useState<Strategy[]>([]);

  useEffect(() => {
    apiFetch<Strategy[]>("/api/v1/strategies").then(setRows).catch(() => setRows([]));
  }, []);

  return (
    <div>
      <h2 className="page-title">Strategy Explorer</h2>
      <p className="page-sub">All strategies stored in the research database.</p>
      <ScrollTable>
      <div className="mt-6 overflow-hidden rounded-lg border border-zinc-800">
        <table className="w-full text-left text-sm">
          <thead className="bg-zinc-900/80 text-xs uppercase text-zinc-500">
            <tr>
              <th className="px-4 py-3">Name</th>
              <th className="px-4 py-3">Market</th>
              <th className="px-4 py-3">Category</th>
              <th className="px-4 py-3">TF</th>
              <th className="px-4 py-3">Lifecycle</th>
            </tr>
          </thead>
          <tbody>
            {rows.length === 0 ? (
              <tr>
                <td colSpan={5} className="px-4 py-8 text-zinc-500">
                  No strategies yet — restart API to seed the built-in library.
                </td>
              </tr>
            ) : (
              rows.map((r) => (
                <tr key={r.id} className="border-t border-zinc-800/80">
                  <td className="px-4 py-3 text-zinc-100">
                    <Link href={`/strategies/${r.id}`} className="hover:text-emerald-400">
                      {r.name}
                    </Link>
                  </td>
                  <td className="px-4 py-3">{r.symbol}</td>
                  <td className="px-4 py-3">{r.category}</td>
                  <td className="px-4 py-3">{r.timeframe}</td>
                  <td className="px-4 py-3">{r.lifecycle}</td>
                </tr>
              ))
            )}
          </tbody>
        </table>
      </div>
      </ScrollTable>
    </div>
  );
}