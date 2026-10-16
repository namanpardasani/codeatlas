import { useEffect, useRef, useState } from "react";

interface JobEvent {
  id?: string | number;
  status: "queued" | "running" | "done" | "failed";
  stage: string;
  progress: number;
  error?: string | null;
}

export default function App() {
  const [url, setUrl] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [job, setJob] = useState<JobEvent | null>(null);
  const esRef = useRef<EventSource | null>(null);

  useEffect(() => () => esRef.current?.close(), []);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    setJob(null);
    setSubmitting(true);
    try {
      const res = await fetch("/api/repos", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ url }),
      });
      const body = await res.json();
      if (!res.ok) throw new Error(body.error ?? `Request failed (${res.status})`);
      watch(body.jobId);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Something went wrong");
    } finally {
      setSubmitting(false);
    }
  }

  function watch(jobId: string | number) {
    esRef.current?.close();
    const es = new EventSource(`/api/jobs/${jobId}/events`);
    esRef.current = es;
    es.onmessage = (m) => {
      const data = JSON.parse(m.data) as JobEvent;
      setJob(data);
      if (data.status === "done" || data.status === "failed") es.close();
    };
    es.onerror = () => es.close();
  }

  const failed = job?.status === "failed";
  return (
    <main className="mx-auto max-w-2xl px-4 py-16">
      <h1 className="text-3xl font-bold tracking-tight">CodeAtlas</h1>
      <p className="mt-2 text-slate-600">Paste a public GitHub repo to analyse its architecture.</p>

      <form onSubmit={submit} className="mt-8 flex gap-2">
        <input
          value={url}
          onChange={(e) => setUrl(e.target.value)}
          placeholder="https://github.com/owner/repo"
          className="flex-1 rounded-md border border-slate-300 px-3 py-2 outline-none focus:border-indigo-500"
        />
        <button
          disabled={submitting || !url.trim()}
          className="rounded-md bg-indigo-600 px-4 py-2 font-medium text-white disabled:opacity-50"
        >
          {submitting ? "Starting…" : "Analyse"}
        </button>
      </form>

      {error && <p className="mt-4 text-sm text-red-600">{error}</p>}

      {job && (
        <section className="mt-8" aria-live="polite">
          <div className="flex justify-between text-sm text-slate-600">
            <span className="capitalize">{job.stage}</span>
            <span>{job.progress}%</span>
          </div>
          <div className="mt-1 h-2 overflow-hidden rounded bg-slate-200">
            <div
              className={`h-full transition-all ${failed ? "bg-red-500" : "bg-indigo-600"}`}
              style={{ width: `${job.progress}%` }}
            />
          </div>
          {failed && <p className="mt-2 text-sm text-red-600">{job.error ?? "Analysis failed"}</p>}
          {job.status === "done" && <p className="mt-2 text-sm text-green-700">Analysis complete.</p>}
        </section>
      )}
    </main>
  );
}
