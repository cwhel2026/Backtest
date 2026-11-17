export default function SettingsPage() {
  return (
    <div className="max-w-2xl space-y-6">
      <h2 className="page-title">Settings</h2>
      <section className="rounded-lg border border-zinc-800 bg-[#181b22] p-6 text-sm text-zinc-400">
        <p className="font-medium text-zinc-200">Server-side configuration</p>
        <ul className="mt-3 list-inside list-disc space-y-2">
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