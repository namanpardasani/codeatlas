import { AnimatePresence, motion } from "motion/react";
import { useEffect, useMemo, useRef, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { getFiles, getJob, reanalyze, watchJob, type JobEvent } from "../api";
import { Button, ButtonLink, Compass, Figure, Logo, ProgressBar, Sheet, ThemeToggle } from "../components/ui";
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

/** A tick drawn in green ink (drawn once, when the last stage finishes). */
function Tick({ draw = false }: { draw?: boolean }) {
  return (
    <svg width="18" height="18" viewBox="0 0 18 18" aria-hidden className="text-verified-ink">
      <motion.path
        d="M3 9.5 L7.2 13.5 L15 4.5"
        fill="none"
        stroke="currentColor"
        strokeWidth="2.2"
        strokeLinecap="square"
        initial={draw ? { pathLength: 0 } : false}
        animate={{ pathLength: 1 }}
        transition={{ duration: 0.45, ease: ease.out }}
      />
    </svg>
  );
}

function Counter({ label, value }: { label: string; value: number | null }) {
  const shown = useCountUp(value);
  return <Figure label={label} value={shown === null ? "—" : shown.toLocaleString()} />;
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
    <div className="min-h-screen bg-table text-table-ink">
      <header className="mx-auto flex max-w-6xl items-center gap-3 px-4 py-5 sm:px-6">
        <Link to="/" aria-label="CodeAtlas home" className="rounded-ui"><Logo needle={running && !failed ? "hunt" : "still"} /></Link>
        {repoName && <><span aria-hidden className="text-table-muted">/</span><span className="font-display text-[19px] italic">{repoName}</span></>}
        <ThemeToggle className="ml-auto" />
      </header>

      <main className="mx-auto grid max-w-6xl grid-cols-[minmax(0,1fr)] items-start gap-8 px-4 pb-16 pt-6 sm:px-6 lg:grid-cols-[minmax(0,1.35fr)_minmax(0,1fr)]">
        <Sheet as="section" aria-live="polite" className="px-5 py-8 sm:px-9">
          <div className="flex items-start justify-between gap-6">
            <div>
              <p className={`mono-label ${failed ? "text-signal-ink" : done ? "text-verified-ink" : ""}`}>
                {failed ? "Survey stopped" : done ? "Survey complete" : `Surveying · step ${Math.min(idx + 1, STAGES.length)} of ${STAGES.length}`}
              </p>
              <h1 className="text-title mt-3 text-ink">{failed ? "The analysis could not be finished" : done ? "Your map is drawn" : current.title}</h1>
              <p className="mt-3 max-w-md text-ink-2">
                {failed ? ev?.error ?? "Something went wrong." : done ? "Taking you to the overview." : "Usually under a minute. You can close this page; the survey keeps going."}
              </p>
            </div>
            <Compass size={76} mode={running && !failed ? "hunt" : "still"} className="hidden shrink-0 text-ink sm:block" title={running && !failed ? "Compass searching" : "Compass"} />
          </div>

          <div className="mt-8 flex items-center gap-4">
            <div className="flex-1"><ProgressBar value={done ? 100 : ev?.progress ?? 0} failed={failed} label="Analysis progress" /></div>
            <span className="w-12 text-right font-mono text-small text-ink">{done ? 100 : ev?.progress ?? 0}%</span>
          </div>

          <ol className="mt-8 border-t-2 border-ink">
            {STAGES.map((s, i) => {
              const state = failed && i === idx ? "failed" : i < idx ? "done" : i === idx && !done ? "active" : "queued";
              const secs = durations[s.id] !== undefined ? durations[s.id]! / 1000 : null;
              return (
                <li key={s.id} className={`grid grid-cols-[28px_minmax(0,1fr)_auto] items-center gap-3 border-b border-rule px-1 py-3 ${state === "active" ? "bg-hl-soft/70" : ""}`}>
                  <span className="flex justify-center">
                    {state === "done" && <Tick draw={done && i === STAGES.length - 1} />}
                    {state === "active" && <span aria-hidden className="anim-soft-pulse size-2.5 rounded-full bg-signal" />}
                    {state === "queued" && <span aria-hidden className="font-mono text-[11px] text-pencil">{String(i + 1).padStart(2, "0")}</span>}
                    {state === "failed" && <span aria-hidden className="font-mono text-signal-ink">✕</span>}
                  </span>
                  <div className="min-w-0">
                    <div className={`text-[15px] ${state === "queued" ? "text-pencil" : state === "failed" ? "text-signal-ink" : "font-medium text-ink"}`}>{s.name}</div>
                    {state === "active" && s.id === "parse" && parsed !== null && filesTotal && (
                      <div className="font-mono text-small text-ink-2">about {parsed} of {filesTotal} files</div>
                    )}
                    {state === "failed" && <div className="text-small text-signal-ink">{ev?.error}</div>}
                  </div>
                  <span className="font-mono text-small text-pencil">
                    {state === "done" && secs !== null ? (secs < 0.1 ? "<0.1 s" : `${secs.toFixed(1)} s`) : state === "active" ? <span className="text-ink">working</span> : ""}
                  </span>
                </li>
              );
            })}
          </ol>

          <div className="mt-6 flex items-center gap-4">
            {done && <ButtonLink to={`/repo/${repoId}/overview`}>Open the overview</ButtonLink>}
            {failed && <Button onClick={retry}>Try again</Button>}
          </div>
        </Sheet>

        <aside className="flex flex-col gap-8 lg:pt-6">
          <Sheet tilt={-0.8} className="p-6">
            <div className="mono-label">Found so far</div>
            <div className="mt-4 grid grid-cols-3 gap-4">
              <Counter label="Files" value={counts?.files ?? filesTotal} />
              <Counter label="Symbols" value={counts?.symbols ?? null} />
              <Counter label="Imports" value={counts?.imports ?? null} />
            </div>
          </Sheet>

          <div className="rounded-ui border border-table-line bg-table-2">
            <div className="border-b border-table-line px-4 py-2 font-mono text-[11px] uppercase tracking-[0.12em] text-table-muted">worker log</div>
            <div className="h-52 overflow-y-auto p-4 font-mono text-[12.5px] leading-relaxed" role="log" aria-label="worker log">
              <AnimatePresence initial={false}>
                {log.map((l, i) => (
                  <motion.div key={i} initial={{ opacity: 0 }} animate={{ opacity: 1 }} transition={{ duration: dur.base }} className={l.warn ? "text-table-signal" : "text-table-ink"}>
                    <span className="text-table-muted">{l.t}</span> {l.text}
                  </motion.div>
                ))}
              </AnimatePresence>
              {log.length === 0 && <span className="text-table-muted">waiting for the worker…</span>}
            </div>
          </div>

          <p className="text-wonk text-[15px] leading-snug text-table-muted">
            Code is read, never run.{me?.limits ? ` Repositories over ${me.limits.maxRepoMb} MB are refused.` : ""} Public repositories only.
          </p>
        </aside>
      </main>
    </div>
  );
}
