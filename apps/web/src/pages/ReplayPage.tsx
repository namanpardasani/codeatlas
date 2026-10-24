import { motion } from "motion/react";
import { useState } from "react";
import { Link } from "react-router-dom";
import { Badge, Button, Logo, Sheet, Stamp, ThemeToggle } from "../components/ui";
import data from "../data/replays.json";
import { GITHUB } from "../features/landing/Footer";
import { useMotionOff } from "../hooks/useMotionOff";
import { ease } from "../ui/motion";

interface Replay {
  id: string; repo: string; outcome: "hit" | "miss"; note: string;
  inducing: { sha: string; subject: string; time: number };
  fix: { sha: string; subject: string; time: number; files: string[] };
  changed: { path: string; category: string; symbols: string[] }[];
  predicted: { path: string; score: number; distance: number; why: string[] }[];
  fix_ranks: Record<string, number | null>;
  risk: { score: number; label: string; top: string[] } | null;
  tests: string | null;
}

const REPLAYS = (data as unknown as { replays: Replay[] }).replays;   // generated JSON: shape checked by its generator
const day = (t: number) => new Date(t * 1000).toISOString().slice(0, 10);

/** Replay: run Blast Radius on a real commit that introduced a bug (with only the history before it), then reveal
 *  where the bug was actually fixed later. One of the three case files is an honest miss. */
export default function ReplayPage() {
  const off = useMotionOff();
  const [idx, setIdx] = useState(0);
  const [revealed, setRevealed] = useState(false);
  const r = REPLAYS[idx]!;
  const fixFiles = new Set(Object.keys(r.fix_ranks));
  const pick = (i: number) => { setIdx(i); setRevealed(false); };
  const bestRank = Math.min(...Object.values(r.fix_ranks).map((v) => v ?? Infinity));

  return (
    <div className="min-h-screen bg-table pb-20 text-table-ink">
      <header className="mx-auto flex max-w-6xl items-center gap-4 px-4 py-5 sm:px-6">
        <Link to="/" aria-label="CodeAtlas home" className="rounded-ui"><Logo /></Link>
        <span className="text-table-muted" aria-hidden>/</span>
        <span className="font-display text-[19px] italic">Replay</span>
        <ThemeToggle className="ml-auto" />
      </header>

      <main className="mx-auto flex max-w-6xl flex-col gap-10 px-4 pt-8 sm:px-6">
        <div className="max-w-3xl">
          <p className="mono-label text-table-muted">Proved on history</p>
          <h1 className="mt-4 font-display text-[clamp(34px,5vw,60px)] font-semibold leading-[0.98] tracking-[-0.04em]">Would it have seen the bug <span className="text-wonk text-signal">coming</span>?</h1>
          <p className="mt-5 text-[16.5px] leading-relaxed text-table-muted">
            Each case is a real commit that later needed a bug fix (found with SZZ, then checked by hand). Blast Radius runs on that commit
            using only the code and history from before it. Then you open the envelope: where was the bug actually fixed? One of the three is a miss.
          </p>
        </div>

        <div>
          <div role="tablist" aria-label="Case files" className="flex flex-wrap items-end gap-1 pl-2">
            {REPLAYS.map((x, i) => {
              const on = i === idx;
              return (
                <button key={x.id} role="tab" aria-selected={on} onClick={() => pick(i)}
                        className={`rounded-t-[3px] px-4 text-left transition-colors ${on ? "paper min-h-14 pt-2.5 text-ink" : "min-h-12 bg-table-2 pt-2 text-table-muted hover:bg-table-3 hover:text-table-ink"}`}>
                  <span className="block font-mono text-[10.5px] uppercase tracking-[0.12em]">Case {i + 1}</span>
                  <span className="block text-[14px] font-semibold">{x.repo}</span>
                </button>
              );
            })}
          </div>

          <Sheet className="rounded-tl-none px-5 py-8 sm:px-9">
            <div className="grid grid-cols-[minmax(0,1fr)] gap-10 lg:grid-cols-[minmax(0,1fr)_minmax(0,1.25fr)]">
              <section className="flex flex-col gap-8">
                <div className="border-t-2 border-ink pt-3">
                  <div className="mono-label">1 · The change, {day(r.inducing.time)}</div>
                  <p className="mt-2 font-display text-[21px] font-semibold leading-snug text-ink">{r.inducing.subject}</p>
                  <p className="mt-1 font-mono text-[12px] text-pencil">{r.inducing.sha.slice(0, 8)}</p>
                  <ul className="mt-4 flex flex-col gap-2 text-small">
                    {r.changed.map((f) => (
                      <li key={f.path}>
                        <span className="flex items-center gap-2">{f.category !== "code" && <Badge>{f.category}</Badge>}<span className="truncate font-mono text-ink">{f.path}</span></span>
                        {f.symbols.length > 0 && <span className="block text-[12.5px] text-pencil">{f.symbols.join(", ")}</span>}
                      </li>
                    ))}
                  </ul>
                  {r.risk && <p className="mt-4 text-small text-ink-2">Risk <span className="font-mono font-semibold">{r.risk.score}</span> ({r.risk.label}){r.tests ? ` · ${r.tests}` : ""}</p>}
                </div>

                <div className={`relative border-t-2 pt-3 ${revealed ? (r.outcome === "hit" ? "border-verified" : "border-signal") : "border-ink"}`}>
                  <div className="mono-label">3 · Where the bug was fixed</div>
                  {!revealed ? (
                    <div className="mt-4 flex flex-col items-start gap-3">
                      <p className="text-wonk text-[17px] text-pencil">Sealed until you look. The prediction in section 2 was made without it.</p>
                      <Button onClick={() => setRevealed(true)}>Open the envelope</Button>
                    </div>
                  ) : (
                    <motion.div initial={off ? false : { opacity: 0 }} animate={{ opacity: 1 }} transition={{ duration: 0.3, ease: ease.out }}>
                      <p className="mt-2 font-display text-[19px] font-semibold leading-snug text-ink">{r.fix.subject}</p>
                      <p className="mt-1 font-mono text-[12px] text-pencil">{r.fix.sha.slice(0, 8)} · {day(r.fix.time)}</p>
                      <ul className="mt-3 flex flex-col gap-1.5 text-small">
                        {Object.entries(r.fix_ranks).map(([f, rank]) => (
                          <li key={f} className="flex flex-wrap items-center gap-2">
                            <span className="truncate font-mono text-ink">{f}</span>
                            {rank ? <Badge tone="success">predicted #{rank}</Badge> : <Badge tone="danger">not predicted</Badge>}
                          </li>
                        ))}
                      </ul>
                      <p className="mt-4 text-[14.5px] leading-relaxed text-ink-2">{r.note}</p>
                      <div className="mt-4">
                        <Stamp tone={r.outcome === "hit" ? "verified" : "signal"} shape="rect" rotate={-6} land label={r.outcome === "hit" ? `Hit: predicted at rank ${bestRank}` : "Miss"}>
                          {r.outcome === "hit" ? `hit · rank ${bestRank}` : "missed"}
                        </Stamp>
                      </div>
                    </motion.div>
                  )}
                </div>
              </section>

              <section className="border-t-2 border-ink pt-3">
                <div className="mono-label">2 · What Blast Radius predicted (files beyond the change)</div>
                <ol className="mt-3 flex flex-col">
                  {r.predicted.map((p, i) => {
                    const hit = revealed && fixFiles.has(p.path);
                    return (
                      <motion.li key={`${r.id}-${p.path}`} initial={off ? false : { opacity: 0 }} animate={{ opacity: 1 }}
                                 transition={{ duration: 0.3, delay: off ? 0 : i * 0.05 }}
                                 className={`relative grid grid-cols-[34px_minmax(0,1fr)_auto] items-baseline gap-2 border-b border-rule px-1 py-2.5 ${hit ? "bg-verified-soft shadow-[inset_3px_0_0_var(--verified)]" : ""}`}>
                        <span className="font-mono text-[12px] text-pencil">#{i + 1}</span>
                        <span className="min-w-0">
                          <span className="block truncate font-mono text-small text-ink">{p.path}</span>
                          <span className="block text-[12.5px] text-ink-2">{p.why[p.why.length - 1]}</span>
                        </span>
                        <span className="flex items-center gap-2">
                          {hit && <span className="font-mono text-[11px] font-semibold uppercase tracking-[0.1em] text-verified-ink">fixed here</span>}
                          <span className="font-mono text-[12px] text-pencil">{p.score.toFixed(2)}</span>
                        </span>
                      </motion.li>
                    );
                  })}
                </ol>
              </section>
            </div>
          </Sheet>
        </div>

        <p className="text-wonk max-w-2xl text-[15.5px] text-table-muted">
          These are illustrations, chosen to include a miss. The aggregate numbers, with the method and the caveats, are in the{" "}
          <a className="text-table-ink underline decoration-signal underline-offset-4" href={`${GITHUB}/blob/main/docs/BLAST_RADIUS_EVAL.md`}>evaluation report</a>.
        </p>
      </main>
    </div>
  );
}
