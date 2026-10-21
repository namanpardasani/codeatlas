import { AnimatePresence, motion } from "framer-motion";
import { useEffect, useMemo, useRef, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { getFiles, getJob, reanalyze, watchJob, type JobEvent } from "../api";
import { Button, Logo, MonoLabel, ProgressBar } from "../components/ui";
import { useCountUp } from "../hooks/useCountUp";
import { useMe } from "../hooks/useMe";
import { dur, ease } from "../ui/motion";

/** The 7 stages the user sees, mapped onto the worker's progress ranges (inventory 30, parsing 50-78, resolving 80, ...). */
const STAGES = [
  { id: "clone", title: "Cloning the repository", name: "Clone", from: 0, to: 29 },
  { id: "read", title: "Reading the files", name: "Read files", from: 30, to: 49 },
  { id: "parse", title: "Parsing every file", name: "Parse code", from: 50, to: 79 },
  { id: "resolve", title: "Resolving imports", name: "Resolve imports", from: 80, to: 81 },
  { id: "graph", title: "Drawing the dependency graph", name: "Dependency graph", from: 82, to: 83 },
  { id: "score", title: "Scoring hotspots", name: "Hotspots", from: 84, to: 89 },
  { id: "index", title: "Indexing for search", name: "Search index", from: 90, to: 99 },
] as const;

export const stageIndex = (progress: number): number => {
  const i = STAGES.findIndex((s) => progress >= s.from && progress <= s.to);
  return i === -1 ? (progress >= 100 ? STAGES.length : 0) : i;
};

interface LogLine {
  t: string;
  text: string;
  warn?: boolean;
}

const clock = () => new Date().toLocaleTimeString([], { hour12: false });

function Check({ draw = false }: { draw?: boolean }) {
  return (
    <svg width="14" height="14" viewBox="0 0 14 14" aria-hidden>
      <motion.path
        d="M2.5 7.5 L5.8 10.5 L11.5 3.8"
        fill="none"
        stroke="var(--color-cyan)"
        strokeWidth="2"
        strokeLinecap="round"
        strokeLinejoin="round"
        initial={draw ? { pathLength: 0 } : false}
        animate={{ pathLength: 1 }}
        transition={{ duration: 0.45, ease: ease.out }}
      />
    </svg>
  );
}

function Counter({ label, value }: { label: string; value: number | null }) {
  const shown = useCountUp(value);
  return (
    <div className="rounded-card border border-border bg-surface p-4">
      <div className="text-[12px] text-muted">{label}</div>
      <div className="mt-1 font-display text-[28px] font-bold leading-none tabular-nums text-text">{shown === null ? "—" : shown.toLocaleString()}</div>
    </div>
  );
}

export default function Progress() {
  const { repoId = "", jobId = "" } = useParams();
  const navigate = useNavigate();
  const { me } = useMe();
  const [ev, setEv] = useState<JobEvent | null>(null);
  const [log, setLog] = useState<LogLine[]>([]);
  const [filesTotal, setFilesTotal] = useState<number | null>(null);
  const [counts, setCounts] = useState<{ files: number; symbols: number; imports: number } | null>(null);
  const [repoName, setRepoName] = useState<string | null>(null);
  const started = useRef<Record<string, number>>({});
  const [durations, setDurations] = useState<Record<string, number>>({});
  const lastLogged = useRef<string>("");

  // live events (SSE)
  useEffect(() => {
    return watchJob(jobId, (e) => {
      setEv(e);
      const key = `${e.status}|${e.stage}`;
      if (key !== lastLogged.current) {
        lastLogged.current = key;
        setLog((l) => [...l.slice(-40), { t: clock(), text: e.status === "failed" ? `failed: ${e.error ?? "unknown error"}` : `${e.stage} (${e.progress}%)`, warn: e.status === "failed" }]);
      }
      const idx = e.status === "done" ? STAGES.length : stageIndex(e.progress);
      const now = Date.now();
      STAGES.forEach((s, i) => {
        if (i === idx && started.current[s.id] === undefined) started.current[s.id] = now;
        if (i < idx && started.current[s.id] !== undefined && durations[s.id] === undefined) {
          const ms = now - started.current[s.id]!;
          setDurations((d) => (d[s.id] === undefined ? { ...d, [s.id]: ms } : d));
        }
      });
    });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [jobId]);

  // counters and file total: existing endpoints, polled while the job runs
  const running = !ev || ev.status === "queued" || ev.status === "running";
  useEffect(() => {
    let stop = false;
    const tick = async () => {
      try {
        const [job, files] = await Promise.all([getJob(jobId), getFiles(repoId).catch(() => [])]);
        if (stop) return;
        setRepoName(job.full_name);
        setFilesTotal(job.files_total);
        if (files.length) setCounts({ files: files.length, symbols: files.reduce((a, f) => a + f.symbol_count, 0), imports: files.reduce((a, f) => a + f.import_count, 0) });
      } catch {
        /* the counters are decoration; the stream is the truth */
      }
      if (!stop && running) setTimeout(tick, 2500);
    };
    void tick();
    return () => {
      stop = true;
    };
  }, [jobId, repoId, running]);

  const done = ev?.status === "done";
  const failed = ev?.status === "failed";
  const idx = done ? STAGES.length : stageIndex(ev?.progress ?? 0);
  const current = STAGES[Math.min(idx, STAGES.length - 1)]!;

  // finish: draw the check, then go to the overview
  useEffect(() => {
    if (!done) return;
    const t = setTimeout(() => navigate(`/repo/${repoId}/overview`), 800);
    return () => clearTimeout(t);
  }, [done, navigate, repoId]);

  // derived live count for the parsing stage (the worker reports a percentage, not a file count)
  const parsed = useMemo(() => {
    if (!filesTotal || !ev) return null;
    const frac = Math.max(0, Math.min(1, (ev.progress - 50) / 28));
    return Math.round(filesTotal * frac);
  }, [filesTotal, ev]);

  async function retry() {
    try {
      const r = await reanalyze(repoId, "full");
      navigate(`/analyze/${repoId}/${r.jobId}`, { replace: true });
      window.location.reload();
    } catch {
      /* the page still shows the original failure */
    }
  }

  return (
    <div className="min-h-screen bg-bg">
      <header className="mx-auto flex max-w-6xl items-center gap-4 px-6 py-5">
        <Link to="/" aria-label="CodeAtlas home" className="rounded-ui"><Logo /></Link>
        {repoName && <span className="font-mono text-small text-text-2">/ {repoName}</span>}
      </header>

      <main className="mx-auto grid max-w-6xl gap-8 px-6 pb-16 pt-6 lg:grid-cols-[1.4fr_1fr]">
        <section aria-live="polite">
          <MonoLabel>{failed ? "MAPPING · STOPPED" : done ? "MAPPING · COMPLETE" : `MAPPING · STAGE ${Math.min(idx + 1, STAGES.length)} OF ${STAGES.length}`}</MonoLabel>
          <h1 className="mt-3 text-page">{failed ? "The map could not be finished" : done ? "Map ready" : current.title}</h1>
          <p className="mt-2 text-text-3">
            {failed ? ev?.error ?? "Something went wrong." : done ? "Taking you to the overview." : "You can leave; we'll keep going."}
          </p>

          <div className="mt-8 flex items-center gap-4">
            <div className="flex-1"><ProgressBar value={done ? 100 : ev?.progress ?? 0} failed={failed} running={!done && !failed} /></div>
            <span className="w-12 text-right font-mono text-small text-text-3">{done ? 100 : ev?.progress ?? 0}%</span>
          </div>

          <ol className="mt-8 overflow-hidden rounded-panel border border-border bg-surface">
            {STAGES.map((s, i) => {
              const state = failed && i === idx ? "failed" : i < idx ? "done" : i === idx && !done ? "active" : "queued";
              return (
                <li
                  key={s.id}
                  className={`flex items-center gap-4 border-b border-line px-5 py-4 last:border-b-0 ${state === "active" ? "bg-cyan-tint" : ""}`}
                >
                  <span className="flex size-6 shrink-0 items-center justify-center">
                    {state === "done" && (
                      <span className="flex size-6 items-center justify-center rounded-full bg-cyan-bg"><Check draw={done && i === STAGES.length - 1} /></span>
                    )}
                    {state === "active" && <span aria-hidden className="anim-spin size-5 rounded-full border-2 border-cyan-bg border-t-cyan" />}
                    {state === "queued" && <span aria-hidden className="size-5 rounded-full border border-dashed border-faint" />}
                    {state === "failed" && <span aria-hidden className="size-5 rounded-full border-2 border-error" />}
                  </span>
                  <div className="min-w-0 flex-1">
                    <div className={`text-body ${state === "queued" ? "text-dim" : state === "failed" ? "text-error" : "text-text"}`}>{s.name}</div>
                    {state === "active" && s.id === "parse" && parsed !== null && filesTotal && (
                      <div className="font-mono text-small text-cyan-soft">~{parsed} / {filesTotal} files</div>
                    )}
                    {state === "failed" && <div className="text-small text-error">{ev?.error}</div>}
                  </div>
                  {state === "done" && durations[s.id] !== undefined && <span className="font-mono text-small text-muted">{(durations[s.id]! / 1000).toFixed(1)}s</span>}
                  {state === "active" && <span className="anim-soft-pulse font-mono text-small text-cyan-soft">running</span>}
                </li>
              );
            })}
          </ol>

          <div className="mt-6 flex items-center gap-4">
            {done && <Link className="text-cyan underline" to={`/repo/${repoId}/overview`}>Go now</Link>}
            {failed && <Button onClick={retry}>Try again</Button>}
          </div>
        </section>

        <aside className="flex flex-col gap-4">
          <div className="grid grid-cols-3 gap-3">
            <Counter label="Files" value={counts?.files ?? filesTotal} />
            <Counter label="Symbols" value={counts?.symbols ?? null} />
            <Counter label="Imports" value={counts?.imports ?? null} />
          </div>

          <div className="overflow-hidden rounded-card border border-border bg-code">
            <div className="flex items-center gap-1.5 border-b border-line bg-bg-raised px-4 py-2.5">
              <span aria-hidden className="size-2.5 rounded-full bg-border-strong" />
              <span aria-hidden className="size-2.5 rounded-full bg-border-strong" />
              <span aria-hidden className="size-2.5 rounded-full bg-border-strong" />
              <span className="ml-2 font-mono text-micro text-muted">worker log</span>
            </div>
            <div className="h-56 overflow-y-auto p-4 font-mono text-[12.5px] leading-relaxed" role="log" aria-label="worker log">
              <AnimatePresence initial={false}>
                {log.map((l, i) => (
                  <motion.div
                    key={i}
                    initial={{ opacity: 0, x: -10 }}
                    animate={{ opacity: 1, x: 0 }}
                    transition={{ duration: dur.base, ease: ease.out }}
                    className={l.warn ? "text-amber-soft" : "text-text-3"}
                  >
                    <span className="text-dim">{l.t}</span> {l.text}
                  </motion.div>
                ))}
              </AnimatePresence>
              {log.length === 0 && <span className="text-dim">waiting for the worker…</span>}
            </div>
          </div>

          <p className="text-small text-muted">
            Code is read, never run.{me?.limits ? ` Repositories larger than ${me.limits.maxRepoMb} MB are refused.` : ""} Public repositories only.
          </p>
        </aside>
      </main>
    </div>
  );
}
