export default function SettingsPage() {
  return (
    <div className="max-w-2xl space-y-6">
      <h2 className="page-title">Settings</h2>
      <section className="rounded-lg border border-zinc-800 bg-[#181b22] p-6 text-sm text-zinc-400">
        <p className="font-medium text-zinc-200">Server-side configuration</p>
        <ul className="mt-3 list-inside list-disc space-y-2">
          <li>
            <code className="text-emerald-400">TWELVEDATA_API_KEY</code> — live/near-live CME 1m bars + last
            print for the paper desk (paid real-time; free plan is delayed)
          </li>
          <li>
            <code className="text-emerald-400">IBKR_HOST</code> + <code className="text-emerald-400">IBKR_PORT</code>{" "}
            — IB Gateway on the same network as the worker. True live last trade (needs a market-data sub)
          </li>
          <li>
            <code className="text-emerald-400">FINZDATA_API_KEY</code> — FinzData historical futures (free =
            daily only; paid market unlocks 1m/5m)
          </li>
          <li>
            <code className="text-emerald-400">DATABENTO_API_KEY</code> — licensed historical futures data
          </li>
          <li>
            <code className="text-emerald-400">OPENAI_API_KEY</code> +{" "}
            <code className="text-emerald-400">AI_RESEARCH_ENABLED=true</code> — autonomous hypothesis generation
          </li>
          <li>
            <code className="text-emerald-400">SECRET_KEY</code> — JWT signing for API authentication
          </li>
        </ul>
        <p className="mt-4 text-xs text-zinc-500">Edit via <code>.env</code> or your deployment secret store, then restart the API and workers.</p>
      </section>
    </div>
  );
}