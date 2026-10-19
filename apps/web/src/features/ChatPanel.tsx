import { Fragment, useEffect, useRef, useState } from "react";
import { streamChat, type ChatChunkInfo, type ChatCitation, type ChatEvent } from "../api";
import { Badge, Button, Panel } from "../components/ui";
import type { ViewerTarget } from "./CodeViewer";

interface Turn {
  question: string;
  text: string;                          // streamed raw text, replaced by the verified answer on `final`
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

const STAGES: Record<string, string> = {
  rewriting: "Understanding the follow-up…",
  retrieving: "Searching the code…",
  generating: "Writing the answer…",
};

const CITE = /\[((?:C\d+(?::\d+(?:-\d+)?)?)(?:\s*[,;]\s*C\d+(?::\d+(?:-\d+)?)?)*)\]/g;

/** Render answer text, turning [C2] / [C2:10-20] into buttons that open the file at those lines. */
function AnswerText({ text, citations, onOpen }: { text: string; citations: ChatCitation[]; onOpen: (t: ViewerTarget) => void }) {
  const find = (ref: string): ChatCitation | undefined => {
    const m = /^(C\d+)(?::(\d+)(?:-(\d+))?)?$/.exec(ref.trim());
    if (!m) return undefined;
    const [, label, s, e] = m;
    return citations.find((c) => c.label === label && (s === undefined || (c.start_line === +s && c.end_line === +(e ?? s))))
      ?? citations.find((c) => c.label === label);
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
    <p className="whitespace-pre-wrap">
      {parts.map((p, i) => {
        if (typeof p === "string") return <Fragment key={i}>{p}</Fragment>;
        const c = find(p.ref);
        if (!c) return <Fragment key={i}>[{p.ref}]</Fragment>;
        return (
          <button key={i} className={`mx-0.5 rounded-ui bg-subtle px-gap font-mono text-small ${c.inferred ? "text-muted" : "text-info"}`}
                  title={`${c.path}:${c.start_line}-${c.end_line}${c.inferred ? " (matched automatically: the model did not cite this)" : ""}`}
                  onClick={() => onOpen({ path: c.path, start: c.start_line, end: c.end_line })}>
            {c.inferred ? "≈" : ""}{p.ref}
          </button>
        );
      })}
    </p>
  );
}

function errorText(e: NonNullable<Turn["error"]>): string {
  const wait = e.retry_after ? ` Try again in ${e.retry_after >= 3600 ? Math.round(e.retry_after / 3600) + " h" : Math.max(1, Math.round(e.retry_after / 60)) + " min"}.` : "";
  return `${e.message}${e.kind === "quota" || e.kind === "rate_limit" ? wait : ""}`;
}

export function ChatPanel({ repoId, onOpen }: { repoId: string; onOpen: (t: ViewerTarget) => void }) {
  const [turns, setTurns] = useState<Turn[]>([]);
  const [question, setQuestion] = useState("");
  const [busy, setBusy] = useState(false);
  const session = useRef<string | undefined>(undefined);
  const abort = useRef<AbortController | null>(null);

  useEffect(() => () => abort.current?.abort(), []);

  const patchLast = (f: (t: Turn) => Turn) => setTurns((ts) => ts.map((t, i) => (i === ts.length - 1 ? f(t) : t)));

  function onEvent(e: ChatEvent) {
    if (e.type === "session") session.current = e.session_id;
    else if (e.type === "status") patchLast((t) => ({ ...t, stage: STAGES[e.stage] ?? e.stage }));
    else if (e.type === "retrieval") patchLast((t) => ({ ...t, retrieved: e.chunks.length }));
    else if (e.type === "delta") patchLast((t) => ({ ...t, text: t.text + e.text }));
    else if (e.type === "final")
      patchLast((t) => ({ ...t, text: e.answer, status: e.status, citations: e.citations, closest: e.closest ?? [],
                          removed: e.removed, issues: e.issues, stage: undefined, done: true }));
    else if (e.type === "error")
      patchLast((t) => ({ ...t, status: "error", error: e, stage: undefined, done: true }));
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

  return (
    <Panel
      title="Ask about this repo"
      actions={turns.length > 0 && !busy ? (
        <Button variant="secondary" onClick={() => { session.current = undefined; setTurns([]); }}>New chat</Button>
      ) : undefined}
    >
      <div className="flex flex-col gap-section">
        {turns.map((t, i) => (
          <div key={i} className="flex flex-col gap-gap">
            <p className="font-semibold">{t.question}</p>

            {!t.done && t.stage && <p className="text-muted">{t.stage}{t.retrieved ? ` (${t.retrieved} excerpts)` : ""}</p>}

            {t.status === "error" && t.error && (
              <p className="text-danger"><Badge tone="danger">{t.error.kind}</Badge> {errorText(t.error)}</p>
            )}

            {t.status === "not_found" && (
              <div className="flex flex-col gap-gap">
                <p><Badge tone="warning">not found</Badge> {t.text}</p>
                {t.closest.length > 0 && (
                  <div className="text-muted">
                    Closest code (probably not an answer):{" "}
                    {t.closest.map((c) => (
                      <button key={c.label} className="mr-gap font-mono text-small text-info"
                              onClick={() => onOpen({ path: c.path, start: c.start_line, end: c.end_line })}>
                        {c.path}:{c.start_line}
                      </button>
                    ))}
                  </div>
                )}
              </div>
            )}

            {t.status !== "error" && t.status !== "not_found" && t.text && (
              <AnswerText text={t.text} citations={t.citations} onOpen={onOpen} />
            )}

            {t.status === "partial" && (
              <p className="text-warning">
                <Badge tone="warning">partly verified</Badge>{" "}
                {t.removed.length > 0 && `${t.removed.length} unsupported statement(s) were removed. `}
                {t.issues.includes("citations_inferred") && "The model did not cite its sources, so citations marked ≈ were matched automatically from the code names it mentions. "}
                {t.issues.includes("uncited_claim") && "Some statements have no citation. "}
                {t.issues.includes("code_not_in_repo") && "A code block is not from the retrieved code."}
              </p>
            )}

            {t.citations.length > 0 && (
              <div className="flex flex-wrap items-center gap-gap text-small text-muted">
                Sources:
                {t.citations.map((c) => (
                  <button key={`${c.label}-${c.start_line}-${c.end_line}`} className="font-mono text-info"
                          onClick={() => onOpen({ path: c.path, start: c.start_line, end: c.end_line })}>
                    {c.inferred ? "≈ " : ""}{c.path}:{c.start_line}–{c.end_line}
                  </button>
                ))}
              </div>
            )}
          </div>
        ))}
      </div>

      <form onSubmit={ask} className="mt-gutter flex gap-gap">
        <input
          value={question}
          onChange={(e) => setQuestion(e.target.value)}
          placeholder={turns.length ? "Ask a follow-up…" : "e.g. How are redirects followed?"}
          maxLength={1000}
          className="flex-1 rounded-ui border border-border bg-surface px-gap py-gap"
        />
        <Button disabled={busy || !question.trim()}>{busy ? "Thinking…" : "Ask"}</Button>
      </form>
    </Panel>
  );
}
