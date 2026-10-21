import { useState } from "react";
import { motion } from "framer-motion";
import {
  AppHeader, Badge, Button, Card, EmptyState, ErrorState, GridLetters, Legend, Logo, MonoLabel, NorthMark, Panel, ProgressBar,
  ScaleBar, ScoreBar, Skeleton, StatCard, Table, type Column,
} from "../components/ui";
import { rise } from "../ui/motion";
import { dur, ease, loop, stagger } from "../ui/motion";

// ---- WCAG contrast, computed live so the board can never claim a pass it does not have --------------------------
const lum = (hex: string) => {
  const [r, g, b] = [1, 3, 5].map((i) => parseInt(hex.slice(i, i + 2), 16) / 255).map((c) => (c <= 0.03928 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4));
  return 0.2126 * r! + 0.7152 * g! + 0.0722 * b!;
};
const contrast = (a: string, b: string) => {
  const [hi, lo] = [lum(a), lum(b)].sort((x, y) => y - x);
  return (hi! + 0.05) / (lo! + 0.05);
};

const SURFACES = [
  ["bg", "#07090C"],
  ["bg-raised", "#0A0E13"],
  ["surface", "#0D1117"],
  ["surface-2", "#111821"],
  ["code", "#05070A"],
  ["line", "#16202B"],
  ["border", "#1F2A36"],
  ["border-strong", "#263445"],
] as const;
const TEXTS = [
  ["text", "#E6EDF3"],
  ["text-2", "#D4DCE5"],
  ["text-3", "#A8B5C4"],
  ["muted", "#8B9BAD"],
  ["dim", "#73849A"],
  ["faint", "#5B6B7D"],
  ["ghost", "#3B4A5C"],
] as const;
const SEMANTIC = [
  ["cyan", "#22D3EE"],
  ["cyan-soft", "#67E8F9"],
  ["cyan-ink", "#04232A"],
  ["cyan-bg", "#06343C"],
  ["cyan-tint", "#071A1F"],
  ["amber", "#F5A524"],
  ["amber-soft", "#FBBF24"],
  ["amber-bg", "#140F06"],
  ["amber-border", "#4A3410"],
  ["error", "#F87171"],
] as const;

function Swatch({ name, hex }: { name: string; hex: string }) {
  return (
    <div className="flex items-center gap-3">
      <span className="size-10 shrink-0 rounded-ui border border-border-strong" style={{ background: hex }} />
      <div>
        <div className="font-mono text-small text-text">{name}</div>
        <div className="font-mono text-micro text-muted">{hex}</div>
      </div>
    </div>
  );
}

function Section({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <section className="flex flex-col gap-4 border-t border-line pt-8">
      <div className="mono-label">{label}</div>
      {children}
    </section>
  );
}

const HOT = [
  { path: "src/requests/models.py", score: 78, why: "complex + changes often", commits: 18 },
  { path: "src/requests/utils.py", score: 64, why: "central + untested", commits: 14 },
  { path: "src/requests/adapters.py", score: 59, why: "in a cycle", commits: 9 },
];
const COLS: Column<(typeof HOT)[number]>[] = [
  { header: "File", render: (r) => <span className="font-mono text-small text-text-2">{r.path}</span> },
  { header: "Score", render: (r) => <ScoreBar value={r.score} /> },
  { header: "Why", render: (r) => <Badge tone={r.score > 70 ? "amber" : "neutral"}>{r.why}</Badge> },
  { header: "Commits", className: "text-right font-mono", render: (r) => r.commits },
];

function Components() {
  const [tab, setTab] = useState("overview");
  return (
    <>
      <Section label="Logo and app header (tabs: click, the underline slides)">
        <div className="overflow-hidden rounded-card border border-border">
          <AppHeader
            repo="psf/requests"
            badge="611c616 · analyzed 2 min ago"
            tabs={[
              { id: "overview", label: "Overview" },
              { id: "map", label: "Map" },
              { id: "hotspots", label: "Hotspots" },
              { id: "ask", label: "Ask" },
              { id: "docs", label: "Docs" },
            ]}
            active={tab}
            onTab={setTab}
            onReanalyze={() => {}}
            onConnect={() => {}}
          />
        </div>
        <div className="flex items-center gap-6">
          <Logo size={40} />
          <Logo size={20} wordmark={false} />
        </div>
      </Section>

      <Section label="Cards, panels, badges">
        <div className="grid gap-4 md:grid-cols-3">
          <Card>
            <MonoLabel>CARD</MonoLabel>
            <p className="mt-2 text-text-3">Surface, 1px border, 14px radius, no shadow.</p>
          </Card>
          <Card variant="risk">
            <MonoLabel>RISK CARD</MonoLabel>
            <p className="mt-2 text-amber-soft">One import cycle across 11 files.</p>
          </Card>
          <Card variant="tint">
            <MonoLabel>ASK THIS REPO</MonoLabel>
            <p className="mt-2 text-cyan-soft">Where are redirects followed?</p>
          </Card>
        </div>
        <Panel title="Panel with actions" label="PLATE 02" actions={<Button variant="secondary">Export</Button>}>
          <div className="flex flex-wrap gap-2">
            <Badge>neutral</Badge>
            <Badge tone="cyan">verified</Badge>
            <Badge tone="amber">hotspot</Badge>
            <Badge tone="error">failed</Badge>
          </div>
        </Panel>
      </Section>

      <Section label="Stat cards (fade up, staggered)">
        <div className="grid grid-cols-2 gap-4 md:grid-cols-5">
          {[
            ["Files", "124"],
            ["Symbols", "807"],
            ["Import edges", "115"],
            ["Cycles", "1"],
            ["Median complexity", "3"],
          ].map(([l, v], i) => (
            <motion.div key={l} {...rise(i)}>
              <StatCard label={l!} value={v} risk={l === "Cycles"} />
            </motion.div>
          ))}
        </div>
      </Section>

      <Section label="Table with score bars (rows are keyboard operable)">
        <Panel title="Top hotspots">
          <Table columns={COLS} rows={HOT} rowKey={(r) => r.path} onRowClick={() => {}} />
        </Panel>
      </Section>

      <Section label="Progress and skeletons">
        <div className="grid gap-6 md:grid-cols-2">
          <div className="flex flex-col gap-3">
            <ProgressBar value={62} />
            <ProgressBar value={100} running={false} />
            <ProgressBar value={40} failed />
          </div>
          <div className="flex flex-col gap-3">
            <Skeleton className="h-5 w-2/3" />
            <Skeleton className="h-4 w-full" />
            <Skeleton className="h-4 w-5/6" />
          </div>
        </div>
      </Section>

      <Section label="Map pieces (legend, scale bar, north mark, grid letters)">
        <div className="bg-line-grid relative h-96 overflow-hidden rounded-card border border-border bg-bg">
          <GridLetters cols={6} rows={4} />
          <div className="absolute left-8 top-10 rounded-card border border-border bg-bg-raised p-4">
            <Legend />
          </div>
          <div className="absolute bottom-3 left-8">
            <ScaleBar />
          </div>
          <div className="absolute bottom-3 right-3">
            <NorthMark />
          </div>
        </div>
      </Section>

      <Section label="Empty and error states">
        <div className="grid gap-6 md:grid-cols-2">
          <Card>
            <EmptyState message="No hotspots yet: this repo has no git history." action={<Button variant="secondary">Re-analyze</Button>} />
          </Card>
          <Card>
            <ErrorState message="Could not reach the search service." action={<Button variant="secondary">Try again</Button>} />
          </Card>
        </div>
      </Section>
    </>
  );
}

export default function Styleguide() {
  return (
    <div className="mx-auto flex max-w-6xl flex-col gap-10 px-6 py-12">
      <header className="flex flex-col gap-3">
        <div className="mono-label">PLATE 00 ——— STYLEGUIDE (temporary route)</div>
        <h1 className="text-page">Design tokens</h1>
        <p className="max-w-xl text-text-3">
          Colour means something: <span className="text-cyan">cyan</span> is structure, navigation and verified;{" "}
          <span className="text-amber">amber</span> is risk, cycles and hotspots; <span className="text-error">red</span> is errors only.
          Everything else is grayscale.
        </p>
      </header>

      <Section label="Surfaces and lines">
        <div className="grid grid-cols-2 gap-4 md:grid-cols-4">
          {SURFACES.map(([n, h]) => (
            <Swatch key={n} name={n} hex={h} />
          ))}
        </div>
      </Section>

      <Section label="Text tones, contrast on bg / surface / surface-2 (WCAG AA needs 4.5)">
        <div className="overflow-x-auto rounded-card border border-border">
          <table className="w-full border-collapse text-small">
            <thead>
              <tr className="text-left text-muted">
                <th className="px-4 py-3 font-medium">token</th>
                <th className="px-4 py-3 font-medium">sample</th>
                {["bg", "surface", "surface-2"].map((b) => (
                  <th key={b} className="px-4 py-3 font-mono font-medium">
                    {b}
                  </th>
                ))}
                <th className="px-4 py-3 font-medium">use as text?</th>
              </tr>
            </thead>
            <tbody>
              {[...TEXTS, ...SEMANTIC.filter(([n]) => ["cyan", "cyan-soft", "amber", "amber-soft", "error"].includes(n))].map(([n, h]) => {
                const ratios = ["#07090C", "#0D1117", "#111821"].map((b) => contrast(h, b));
                const ok = Math.min(...ratios) >= 4.5;
                return (
                  <tr key={n} className="border-t border-line">
                    <td className="px-4 py-3 font-mono text-text">{n}</td>
                    <td className="px-4 py-3" style={{ color: h }}>
                      Any codebase, mapped.
                    </td>
                    {ratios.map((r, i) => (
                      <td key={i} className={`px-4 py-3 font-mono ${r >= 4.5 ? "text-text-3" : "text-amber-soft"}`}>
                        {r.toFixed(2)}
                      </td>
                    ))}
                    <td className="px-4 py-3 font-mono">{ok ? <span className="text-cyan">yes</span> : <span className="text-amber-soft">decoration only</span>}</td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
        <p className="text-small text-muted">
          <span className="font-mono text-text-3">faint</span> and <span className="font-mono text-text-3">ghost</span> fail as text. Use{" "}
          <span className="font-mono text-text-3">dim</span> (#73849A, added) where a board calls for faint text.
        </p>
      </Section>

      <Section label="Semantic colour">
        <div className="grid grid-cols-2 gap-4 md:grid-cols-5">
          {SEMANTIC.map(([n, h]) => (
            <Swatch key={n} name={n} hex={h} />
          ))}
        </div>
      </Section>

      <Section label="Type scale">
        <div className="flex flex-col gap-5">
          <div>
            <div className="mono-label mb-1">hero · Space Grotesk 700 · clamp(44px, 6vw, 76px) · .98 · -0.04em</div>
            <div className="text-hero">
              Any codebase, <span className="text-cyan">mapped</span> in a minute.
            </div>
          </div>
          <div>
            <div className="mono-label mb-1">page title · 44px · -0.03em</div>
            <div className="text-page">Overview</div>
          </div>
          <div>
            <div className="mono-label mb-1">section · 20px</div>
            <div className="text-section">Top hotspots</div>
          </div>
          <div>
            <div className="mono-label mb-1">body · Inter · 15px / 1.6</div>
            <p className="max-w-xl">
              CodeAtlas parses the repository, resolves every import and ranks the files that are riskiest to change. Answers cite the exact lines.
            </p>
          </div>
          <div>
            <div className="mono-label mb-1">small · 13px</div>
            <p className="text-small text-text-3">Analyzed 2 minutes ago from commit abc1234.</p>
          </div>
          <div>
            <div className="mono-label mb-1">mono label · JetBrains Mono 11px · .14em</div>
            <div className="mono-label">PLATE 01 ——— STATIC ANALYSIS FIRST · AI SECOND</div>
            <div className="mt-2 font-mono text-small text-cyan-soft">src/router/index.ts</div>
          </div>
        </div>
      </Section>

      <Section label="Radii and the one shadow">
        <div className="flex flex-wrap items-end gap-6">
          {[
            ["control · 8px", "rounded-ui", "h-14 w-28"],
            ["card · 14px", "rounded-card", "h-20 w-36"],
            ["panel · 18px", "rounded-panel", "h-24 w-44"],
            ["input shell · 16px", "rounded-shell", "h-16 w-56 shadow-deep"],
          ].map(([l, r, s]) => (
            <div key={l} className="flex flex-col gap-2">
              <div className={`border border-border bg-surface ${r} ${s}`} />
              <span className="font-mono text-micro text-muted">{l}</span>
            </div>
          ))}
        </div>
      </Section>

      <Section label="Buttons (min height 44px, focus: Tab to see the cyan outline)">
        <div className="flex flex-wrap items-center gap-4">
          <Button>Map it →</Button>
          <Button variant="secondary">Re-analyze</Button>
          <Button variant="ghost">Cancel</Button>
          <Button disabled>Disabled</Button>
        </div>
      </Section>

      <Section label="Backgrounds">
        <div className="grid gap-4 md:grid-cols-2">
          <div className="bg-dot-grid h-40 rounded-card border border-border bg-bg p-4">
            <span className="mono-label">28px dot grid · landing</span>
          </div>
          <div className="bg-line-grid h-40 rounded-card border border-border bg-bg p-4">
            <span className="mono-label">40px line grid · map canvas</span>
          </div>
        </div>
      </Section>

      <Components />

      <Section label="Motion tokens (src/ui/motion.ts)">
        <ul className="grid gap-1 font-mono text-small text-text-3 md:grid-cols-2">
          <li>ease.out = [{ease.out.join(", ")}]</li>
          <li>
            dur.fast {dur.fast * 1000}ms · base {dur.base * 1000}ms · enter {dur.enter * 1000}ms · bar {dur.bar * 1000}ms
          </li>
          <li>stagger {stagger * 1000}ms</li>
          <li>
            loops: pulse {loop.pulse}s · dash {loop.dash}s · shimmer {loop.shimmer}s · caret {loop.caret}s (all within 1.4-3.2s except caret, a blink)
          </li>
        </ul>
      </Section>
    </div>
  );
}
