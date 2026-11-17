"use client";

import { FormEvent, useState } from "react";
import { useRouter } from "next/navigation";
import { login, setStoredToken } from "@/lib/api";

export default function LoginPage() {
  const router = useRouter();
  const [email, setEmail] = useState("admin@propedge.local");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  async function onSubmit(e: FormEvent) {
    e.preventDefault();
    setLoading(true);
    setError(null);
    try {
      const token = await login(email, password);
      setStoredToken(token.access_token);
      router.push("/");
    } catch {
      setError("Invalid credentials. Use the admin email from .env and your configured password.");
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="flex min-h-screen items-center justify-center bg-[#0e1015] px-4">
      <form
        onSubmit={onSubmit}
        className="w-full max-w-md rounded-xl border border-zinc-800 bg-[#12141a] p-8 shadow-xl"
      >
        <p className="text-xs font-semibold tracking-[0.25em] text-emerald-400">PROP EDGE AI</p>
        <h1 className="mt-2 text-2xl font-medium text-white">Private research login</h1>
        <p className="mt-2 text-sm text-zinc-500">
          Credentials are stored server-side. Default admin is created on first API boot.
        </p>
        <label className="mt-6 block text-sm text-zinc-400">
          Email
          <input
            className="mt-1 w-full rounded-md border border-zinc-700 bg-zinc-900 px-3 py-2 text-white"
            type="email"
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            required
          />
        </label>
        <label className="mt-4 block text-sm text-zinc-400">
          Password
          <input
            className="mt-1 w-full rounded-md border border-zinc-700 bg-zinc-900 px-3 py-2 text-white"
            type="password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            required
          />
        </label>
        {error ? <p className="mt-4 text-sm text-red-400">{error}</p> : null}
        <button
          type="submit"
          disabled={loading}
          className="mt-6 w-full rounded-md bg-emerald-600 px-4 py-2 text-sm font-medium text-white hover:bg-emerald-500 disabled:opacity-50"
        >
          {loading ? "Signing in…" : "Sign in"}
        </button>
      </form>
    </div>
  );
}