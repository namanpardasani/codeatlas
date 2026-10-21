import { lazy, Suspense, useEffect, useMemo, useRef, useState, Fragment } from "react";
import { useSearchParams } from "react-router-dom";
import { streamChat, type ChatChunkInfo, type ChatCitation, type ChatEvent } from "../api";
import { Button, Skeleton } from "../components/ui";
import { SearchPanel } from "../features/SearchPanel";
import type { ViewerTarget } from "../features/CodeViewer";
import { useRepo } from "../hooks/RepoData";

const CodeViewer = lazy(() => import("../features/CodeViewer"));

interface Turn {
  question: string;
  text: string;
  status?: "answered" | "partial" | "not_found" | "error";
  citations: ChatCitation[];
  closest: ChatChunkInfo[];
  removed: string[];
  issues: string[];
  stage?: string;
  retrieved?: number;
  error?: { kind: string; message: string; retry_after: number | null };
  done: boolean;
}

const STAGES: Record<string, string> = { rewriting: "Understanding the follow-up…", retrieving: "Searching the code…", generating: "Writing the answer…" };
const CITE = /\[((?:C\d+(?::\d+(?:-\d+)?)?)(?:\s*[,;]\s*C\d+(?::\d+(?:-\d+)?)?)*)\]/g;

const errorText = (e: NonNullable<Turn["error"]>) => {
  const wait = e.retry_after ? ` Try again in ${e.retry_after >= 3600 ? Math.round(e.retry_after / 3600) + " h" : Math.max(1, Math.round(e.retry_after / 60)) + " min"}.` : "";
  return `${e.message}${e.kind === "quota" || e.kind === "rate_limit" ? wait : ""}`;
};

const CheckIcon = () => (
  <svg width="14" height="14" viewBox="0 0 14 14" aria-hidden className="shrink-0">
    <path d="M2.5 7.5 L5.8 10.5 L11.5 3.8" fill="none" stroke="var(--color-cyan)" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" />
  </svg>
);

const chipKey = (c: ChatCitation) => `${c.path}:${c.start_line}-${c.end_line}`;

/** Answer text with [C2] / [C2:10-20] turned into numbered 22px chips (the number is the citation's position in SOURCES). */
function AnswerText({ text, citations, active, onOpen, caret }: { text: string; citations: ChatCitation[]; active: string | null; onOpen: (c: ChatCitation) => void; caret: boolean }) {
  const order = useMemo(() => {
    const m = new Map<string, number>();
    citations.forEach((c) => m.has(chipKey(c)) || m.set(chipKey(c), m.size + 1));
    return m;
  }, [citations]);
  const find = (ref: string): ChatCitation | undefined => {
    const m = /^(C\d+)(?::(\d+)(?:-(\d+))?)?$/.exec(ref.trim());
    if (!m) return undefined;
    const [, label, s, e] = m;
    return citations.find((c) => c.label === label && (s === undefined || (c.start_line === +s && c.end_line === +(e ?? s)))) ?? citations.find((c) => c.label === label);
  };
  const parts: (string | { ref: string })[] = [];
  let last = 0;
  for (const m of text.matchAll(CITE)) {
    parts.push(text.slice(last, m.index));
    for (const ref of m[1]!.split(/\s*[,;]\s*/)) parts.push({ ref });
    last = m.index! + m[0].length;
  }
  parts.push(text.slice(last));
  return (
    <p className="whitespace-pre-wrap text-[15.5px] leading-[1.7] text-text-2">
      {parts.map((p, i) => {
        if (typeof p === "string") return <Fragment key={i}>{p}</Fragment>;
        const c = find(p.ref);
        if (!c) return <Fragment key={i}>[{p.ref}]</Fragment>;
        const on = active === chipKey(c);
        return (
          <button
            key={i}
            onClick={() => onOpen(c)}
            title={`${c.path}:${c.start_line}-${c.end_line}${c.inferred ? " (matched automatically: the model did not cite this)" : ""}`}
            aria-label={`Citation ${order.get(chipKey(c))}: ${c.path} lines ${c.start_line} to ${c.end_line}`}
            className={`mx-0.5 inline-flex size-[22px] translate-y-[-1px] items-center justify-center rounded-md border font-mono text-[11px] transition-colors duration-150 ${
              on ? "border-cyan bg-cyan-bg text-cyan-soft" : c.inferred ? "border-dashed border-border-strong text-muted hover:text-text" : "border-border bg-surface-2 text-text-3 hover:border-cyan hover:text-cyan-soft"
            }`}
          >
            {order.get(chipKey(c))}
          </button>
        );
      })}
      {caret && <span aria-hidden className="anim-caret ml-0.5 inline-block h-[1.05em] w-[7px] translate-y-[3px] bg-cyan" />}
    </p>
  );
}

export default function AskPage() {
  const { repoId } = useRepo();
  const [params] = useSearchParams();
  const [mode, setMode] = useState<"ask" | "search">("ask");
  const [turns, setTurns] = useState<Turn[]>([]);
  const [question, setQuestion] = useState(params.get("q") ?? "");
  const [busy, setBusy] = useState(false);
  const [viewer, setViewer] = useState<ViewerTarget | null>(null);
  const session = useRef<string | undefined>(undefined);
  const abort = useRef<AbortController | null>(null);
  const bottom = useRef<HTMLDivElement | null>(null);
  const nonce = useRef(0);

  useEffect(() => {
    return () => abort.current?.abort();
  }, []);
  useEffect(() => {
    bottom.current?.scrollIntoView({ behavior: "smooth", block: "end" });
  }, [turns]);

  const open = (t: { path: string; start_line: number; end_line: number }) => setViewer({ path: t.path, start: t.start_line, end: t.end_line, nonce: ++nonce.current });
  const patchLast = (f: (t: Turn) => Turn) => setTurns((ts) => ts.map((t, i) => (i === ts.length - 1 ? f(t) : t)));

  function onEvent(e: ChatEvent) {
    if (e.type === "session") session.current = e.session_id;
    else if (e.type === "status") patchLast((t) => ({ ...t, stage: STAGES[e.stage] ?? e.stage }));
    else if (e.type === "retrieval") patchLast((t) => ({ ...t, retrieved: e.chunks.length }));
    else if (e.type === "delta") patchLast((t) => ({ ...t, text: t.text + e.text }));
    else if (e.type === "final") patchLast((t) => ({ ...t, text: e.answer, status: e.status, citations: e.citations, closest: e.closest ?? [], removed: e.removed, issues: e.issues, stage: undefined, done: true }));
    else if (e.type === "error") patchLast((t) => ({ ...t, status: "error", error: e, stage: undefined, done: true }));
  }

  async function ask(ev: React.FormEvent) {
    ev.preventDefault();
    const q = question.trim();
    if (!q || busy) return;
    setQuestion("");
    setBusy(true);
    setTurns((ts) => [...ts, { question: q, text: "", citations: [], closest: [], removed: [], issues: [], done: false }]);
    abort.current = new AbortController();
    try {
      await streamChat(repoId, { question: q, session_id: session.current }, onEvent, abort.current.signal);
    } catch (err) {
      if ((err as Error).name !== "AbortError")
        patchLast((t) => ({ ...t, status: "error", done: true, error: { kind: "unavailable", message: (err as Error).message, retry_after: null } }));
    } finally {
      patchLast((t) => (t.done ? t : { ...t, done: true }));
      setBusy(false);
    }
  }

  const activeKey = viewer ? `${viewer.path}:${viewer.start}-${viewer.end}` : null;

  return (
    <div className="grid grid-cols-[minmax(0,1fr)] gap-5 lg:grid-cols-[minmax(0,1fr)_minmax(0,1.1fr)]">
      <section className="flex min-h-[70vh] flex-col rounded-panel border border-border bg-surface lg:h-[76vh]" aria-label="Ask">
        <div className="flex items-center justify-between gap-3 border-b border-line px-5 py-3">
          <div className="mono-label">PLATE 04 ——— {mode === "ask" ? "ASK THIS REPO" : "SEARCH THE CODE"}</div>
          <div className="flex items-center gap-2" role="group" aria-label="Mode">
            <Button variant={mode === "ask" ? "primary" : "ghost"} className="!min-h-9 px-3" onClick={() => setMode("ask")}>Ask</Button>
            <Button variant={mode === "search" ? "primary" : "ghost"} className="!min-h-9 px-3" onClick={() => setMode("search")}>Search</Button>
            {mode === "ask" && turns.length > 0 && !busy && (
              <Button variant="ghost" className="!min-h-9 px-3" onClick={() => { session.current = undefined; setTurns([]); }}>New chat</Button>
            )}
          </div>
        </div>

        {mode === "search" ? (
          <div className="min-h-0 flex-1 overflow-y-auto p-5">
            <SearchPanel repoId={repoId} onOpen={(t) => setViewer({ ...t, nonce: ++nonce.current })} />
          </div>
        ) : (
          <>
            <div className="min-h-0 flex-1 overflow-y-auto px-5 py-5" aria-live="polite">
              {turns.length === 0 && (
                <p className="max-w-md text-small text-muted">
                  Ask how something works. Every claim in the answer links to the lines it came from, and anything that cannot be checked against the code is removed.
                </p>
              )}
              <div className="flex flex-col gap-8">
                {turns.map((t, i) => {
                  const verified = t.citations.filter((c) => !c.inferred).length;
                  return (
                    <div key={i} className="flex flex-col gap-4">
                      <div className="flex justify-end">
                        <p className="max-w-[85%] rounded-card bg-surface-2 px-4 py-2.5 text-body text-text">{t.question}</p>
                      </div>

                      {!t.done && t.stage && <p className="anim-soft-pulse font-mono text-small text-muted">{t.stage}{t.retrieved ? ` (${t.retrieved} excerpts)` : ""}</p>}

                      {t.status === "error" && t.error && <p role="alert" className="text-error">{errorText(t.error)}</p>}

                      {t.status === "not_found" && (
                        <div className="flex flex-col gap-2">
                          <p className="text-text-2">{t.text}</p>
                          <p className="text-small text-muted">Try naming a file or function, or ask about one specific behaviour.</p>
                          {t.closest.length > 0 && (
                            <div className="flex flex-wrap items-center gap-2 text-small text-muted">
                              Closest code (probably not an answer):
                              {t.closest.map((c) => (
                                <button key={c.label} className="rounded-md border border-border px-2 py-0.5 font-mono text-[11.5px] text-text-3 hover:border-cyan" onClick={() => open(c)}>
                                  {c.path}:{c.start_line}
                                </button>
                              ))}
                            </div>
                          )}
                        </div>
                      )}

                      {t.status !== "error" && t.status !== "not_found" && (t.text || !t.done) && (
                        <AnswerText text={t.text} citations={t.citations} active={activeKey} onOpen={open} caret={!t.done && !!t.text} />
                      )}

                      {t.status === "partial" && (
                        <p className="text-small text-amber-soft">
                          Partly verified.{" "}
                          {t.removed.length > 0 && `${t.removed.length} unsupported statement(s) were removed. `}
                          {t.issues.includes("citations_inferred") && "Chips with a dashed outline were matched automatically from code names the answer mentions. "}
                          {t.issues.includes("uncited_claim") && "Some statements have no citation."}
                        </p>
                      )}

                      {t.citations.length > 0 && (
                        <div className="flex flex-col gap-2">
                          <div className="flex flex-wrap items-center gap-2">
                            <span className="mono-label mr-1">SOURCES</span>
                            {[...new Map(t.citations.map((c) => [chipKey(c), c])).values()].map((c, n) => {
                              const on = activeKey === chipKey(c);
                              return (
                                <button
                                  key={chipKey(c)}
                                  onClick={() => open(c)}
                                  className={`inline-flex items-center gap-1.5 rounded-md border px-2 py-1 font-mono text-[11.5px] transition-colors duration-150 ${on ? "border-cyan bg-cyan-bg text-cyan-soft" : "border-border bg-surface-2 text-text-3 hover:border-cyan"}`}
                                >
                                  <span className="text-dim">{n + 1}</span>
                                  {c.path.split("/").slice(-2).join("/")}:{c.start_line}–{c.end_line}
                                </button>
                              );
                            })}
                          </div>
                          <p className="flex items-center gap-2 text-small text-text-3">
                            <CheckIcon />
                            {verified} of {t.citations.length} citations verified against the code
                            {verified < t.citations.length && <span className="text-muted"> · {t.citations.length - verified} matched automatically</span>}
                          </p>
                        </div>
                      )}
                    </div>
                  );
                })}
              </div>
              <div ref={bottom} />
            </div>

            <form onSubmit={ask} className="border-t border-line p-4">
              <div className="flex items-center gap-2 rounded-shell border border-border-strong bg-bg p-1.5 pl-4 focus-within:border-cyan">
                <label htmlFor="q" className="sr-only">Your question</label>
                <input
                  id="q"
                  value={question}
                  onChange={(e) => setQuestion(e.target.value)}
                  placeholder={turns.length ? "Ask a follow-up…" : "e.g. How are redirects followed?"}
                  maxLength={1000}
                  autoComplete="off"
                  className="min-w-0 flex-1 bg-transparent py-2.5 text-body text-text outline-none placeholder:text-dim"
                />
                <Button type="submit" disabled={busy || !question.trim()} aria-label="Send question" className="!min-h-10 px-4">
                  {busy ? "Thinking…" : "Send →"}
                </Button>
              </div>
            </form>
          </>
        )}
      </section>

      <section className="min-h-[50vh] lg:h-[76vh]" aria-label="Code viewer">
        {viewer ? (
          <Suspense fallback={<Skeleton className="h-full w-full rounded-card" />}>
            <CodeViewer repoId={repoId} target={viewer} onClose={() => setViewer(null)} />
          </Suspense>
        ) : (
          <div className="flex h-full min-h-[50vh] items-center justify-center rounded-card border border-dashed border-border-strong bg-code p-8 text-center">
            <p className="max-w-xs text-small text-muted">Click a numbered citation to see the exact lines it points to.</p>
          </div>
        )}
      </section>
    </div>
  );
}
