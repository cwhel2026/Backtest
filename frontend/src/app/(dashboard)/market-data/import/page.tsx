"use client";

import Link from "next/link";
import { useCallback, useEffect, useState } from "react";
import { apiFetch, getStoredToken } from "@/lib/api";
import { Button } from "@/components/ui/Button";
import { Card } from "@/components/ui/Card";

type BatchJob = {
  id: string;
  state: string;
  dataset?: string;
  schema?: string;
  symbols?: string;
  start?: string;
  end?: string;
  size_bytes?: number;
};

const CHUNK = 4 * 1024 * 1024;

export default function ImportHistoricalDataPage() {
  const [mode, setMode] = useState<"batch" | "upload">("batch");
  const [jobs, setJobs] = useState<BatchJob[]>([]);
  const [jobsNote, setJobsNote] = useState<string>("");
  const [configured, setConfigured] = useState(false);
  const [selectedJob, setSelectedJob] = useState<string>("");
  const [uploadFiles, setUploadFiles] = useState<FileList | null>(null);
  const [progress, setProgress] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const loadJobs = useCallback(() => {
    apiFetch<{ jobs: BatchJob[]; note?: string; configured?: boolean }>("/api/v1/market-data/databento/batch-jobs")
      .then((r) => {
        setJobs(r.jobs || []);
        setJobsNote(r.note || "");
        setConfigured(!!r.configured);
      })
      .catch(() => setJobs([]));
  }, []);

  useEffect(() => {
    loadJobs();
  }, [loadJobs]);

  async function importBatch() {
    if (!selectedJob) return;
    setBusy(true);
    setProgress("Queuing download of your purchased batch…");
    try {
      const res = await apiFetch<{ message?: string; job_id?: string }>("/api/v1/market-data/databento/batch-import", {
        method: "POST",
        body: JSON.stringify({ databento_batch_job_id: selectedJob }),
      });
      setProgress(res.message || "Import started. Open AI Research for live status.");
    } catch (e) {
      setProgress(String(e));
    } finally {
      setBusy(false);
    }
  }

  async function uploadFromIphone() {
    if (!uploadFiles?.length) return;
    setBusy(true);
    setProgress("Preparing upload…");
    const specs = Array.from(uploadFiles).map((f) => ({ name: f.name, size: f.size }));
    try {
      const init = await apiFetch<{ upload_id: string }>("/api/v1/market-data/databento/upload/init", {
        method: "POST",
        body: JSON.stringify({ files: specs }),
      });
      const uploadId = init.upload_id;
      const token = getStoredToken();
      for (const file of Array.from(uploadFiles)) {
        const total = Math.ceil(file.size / CHUNK) || 1;
        for (let index = 0; index < total; index++) {
          const blob = file.slice(index * CHUNK, Math.min(file.size, (index + 1) * CHUNK));
          const fd = new FormData();
          fd.append("file", blob, file.name);
          const url = `/api/v1/market-data/databento/upload/${uploadId}/chunk?file_name=${encodeURIComponent(file.name)}&index=${index}&total=${total}`;
          const res = await fetch(url, {
            method: "POST",
            headers: token ? { Authorization: `Bearer ${token}` } : {},
            body: fd,
          });
          if (!res.ok) throw new Error(await res.text());
          const pct = Math.round(((index + 1) / total) * 100);
          setProgress(`Uploading ${file.name}… ${pct}%`);
        }
      }
      setProgress("Assembling files — starting validation…");
      const done = await apiFetch<{ message?: string }>("/api/v1/market-data/databento/upload/complete", {
        method: "POST",
        body: JSON.stringify({ upload_id: uploadId }),
      });
      setProgress(done.message || "Processing started — check AI Research.");
    } catch (e) {
      setProgress(String(e));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="space-y-6">
      <header>
        <h1 className="page-title">Import historical data</h1>
        <p className="page-sub">MNQ · MES · MGC · Nov 2021 – Nov 2026 · DBN/zstd from your Databento purchase.</p>
      </header>

      <div className="grid grid-cols-2 gap-2">
        <Button variant={mode === "batch" ? "primary" : "secondary"} onClick={() => setMode("batch")}>
          Databento purchase
        </Button>
        <Button variant={mode === "upload" ? "primary" : "secondary"} onClick={() => setMode("upload")}>
          Upload from iPhone
        </Button>
      </div>

      {mode === "batch" ? (
        <section className="space-y-3">
          <Card className="text-sm text-zinc-300">
            <p>
              Retrieves a <strong className="text-zinc-100">batch you already paid for</strong> using the server API key. Does
              not create a new data request.
            </p>
            {!configured ? (
              <p className="mt-2 text-xs text-amber-300">Add DATABENTO_API_KEY on Railway to list batches.</p>
            ) : (
              <p className="mt-2 text-xs text-zinc-500">{jobsNote}</p>
            )}
          </Card>
          {jobs.length === 0 ? (
            <p className="text-sm text-zinc-500">No batch jobs listed yet. After you purchase on Databento, tap Refresh.</p>
          ) : (
            <ul className="space-y-2">
              {jobs.map((j) => (
                <li key={j.id}>
                  <button
                    type="button"
                    onClick={() => setSelectedJob(j.id)}
                    className={`w-full rounded-2xl border px-4 py-3 text-left text-sm ${
                      selectedJob === j.id ? "border-[var(--accent)] bg-[var(--accent-muted)]" : "border-[var(--border)]"
                    }`}
                  >
                    <span className="font-medium text-zinc-100">{j.id.slice(0, 12)}…</span>
                    <span className="ml-2 text-xs text-zinc-500">
                      {j.state === "done" ? "Ready to import" : j.state} · {j.schema} · {String(j.symbols)}
                    </span>
                  </button>
                </li>
              ))}
            </ul>
          )}
          <div className="flex gap-2">
            <Button variant="secondary" className="flex-1" onClick={loadJobs}>
              Refresh list
            </Button>
            <Button
              className="flex-1"
              disabled={!selectedJob || busy || jobs.find((j) => j.id === selectedJob)?.state !== "done"}
              onClick={importBatch}
            >
              Import selected batch
            </Button>
          </div>
        </section>
      ) : (
        <section className="space-y-3">
          <Card className="text-sm text-zinc-300">
            <p>
              Download DBN / DBN.zst files from Databento to the <strong className="text-zinc-100">Files</strong> app, then pick
              them here. Large files upload in chunks so you can retry after a dropped connection.
            </p>
          </Card>
          <input
            type="file"
            accept=".dbn,.zst,application/octet-stream"
            multiple
            className="w-full text-sm text-zinc-400"
            onChange={(e) => setUploadFiles(e.target.files)}
          />
          {uploadFiles?.length ? (
            <p className="text-xs text-zinc-500">
              {uploadFiles.length} file(s) ·{" "}
              {(Array.from(uploadFiles).reduce((a, f) => a + f.size, 0) / (1024 * 1024)).toFixed(1)} MB total
            </p>
          ) : null}
          <Button fullWidth disabled={!uploadFiles?.length || busy} onClick={uploadFromIphone}>
            {busy ? "Working…" : "Upload and import"}
          </Button>
        </section>
      )}

      {progress ? <Card className="text-sm text-zinc-300">{progress}</Card> : null}

      <Link href="/research" className="block text-sm text-[var(--accent)]">
        Track import progress → AI Research
      </Link>
      <Link href="/market-data" className="block text-sm text-zinc-500">
        ← Market data library
      </Link>
    </div>
  );
}