import { useState } from "react";
import {
  Arrow, Badge, Button, Card, CodeBlock, Compass, EmptyState, Figure, Legend, Logo, MarginNote, PageHead, Panel,
  ProgressBar, ScoreBar, Segmented, Sheet, Skeleton, Stamp, Table, ThemeToggle,
} from "../components/ui";

/** Dev-only: the whole kit on one page, on the table and on paper, in the current theme. */
const SWATCHES: [string, string][] = [
  ["table", "--table"], ["paper", "--paper"], ["paper-2", "--paper-2"], ["ink", "--ink"], ["pencil", "--pencil"], ["rule", "--rule"],
  ["signal", "--signal"], ["verified", "--verified"], ["caution", "--caution"], ["hl", "--hl"],
];

export default function Styleguide() {
  const [seg, setSeg] = useState<"files" | "folders">("files");
  return (
    <div className="min-h-screen bg-table pb-24 text-table-ink">
      <header className="mx-auto flex max-w-6xl items-center gap-4 px-4 py-5 sm:px-6">
        <Logo needle="track" />
        <span className="mono-label text-table-muted">styleguide · v4 paper atlas</span>
        <ThemeToggle className="ml-auto" />
      </header>

      <main className="mx-auto flex max-w-6xl flex-col gap-14 px-4 sm:px-6">
        {/* on the table */}
        <section className="grid gap-10 lg:grid-cols-[1.2fr_1fr]">
          <div>
            <div className="mono-label text-table-muted">Display · Fraunces</div>
            <p className="text-display mt-3">Know what a change <span className="text-wonk text-signal">will break</span>.</p>
            <p className="mt-6 max-w-lg text-[18px] text-table-muted">Body · IBM Plex Sans. Paths and numbers · <span className="font-mono text-table-ink">IBM Plex Mono src/requests/models.py</span></p>
            <div className="mt-8 flex flex-wrap items-center gap-4">
              <Button size="lg">Draw the map</Button>
              <Button variant="secondary" size="lg">Secondary</Button>
              <Button variant="arrow" size="lg" className="text-table-ink">Replay a real bug <Arrow /></Button>
            </div>
            <div className="mt-8 flex items-center gap-6 text-table-ink">
              <Compass size={56} mode="track" title="Compass (tracks the pointer)" />
              <Compass size={56} mode="hunt" title="Compass (hunting: analysing)" />
              <MarginNote tone="hl" arrow="left">the needle follows you</MarginNote>
            </div>
          </div>
          <div className="grid grid-cols-5 gap-3 self-start">
            {SWATCHES.map(([n, v]) => (
              <div key={n} className="font-mono text-[11px] text-table-muted">
                <div className="h-14 rounded-sm border border-table-line" style={{ background: `var(${v})` }} />
                <div className="mt-1">{n}</div>
              </div>
            ))}
          </div>
        </section>

        {/* sheets */}
        <section className="grid items-start gap-8 md:grid-cols-3">
          <Sheet tilt={-1.2} tape className="p-6">
            <div className="mono-label">Sheet · tilt −1.2 · tape</div>
            <h3 className="text-heading mt-2">If I change models.py, what else moves?</h3>
            <p className="mt-2 text-small text-ink-2">Calls, imports and files that change together, each with the path that explains it.</p>
          </Sheet>
          <Sheet tilt={0.8} fold className="p-6">
            <div className="mono-label">Sheet · tilt 0.8 · fold</div>
            <Figure label="MRR · 23 hand-confirmed pairs" value="0.831" hint="vs 0.670 for changed-files-only" />
          </Sheet>
          <Sheet className="relative p-6">
            <div className="mono-label">Sheet · straight (functional)</div>
            <div className="mt-3 flex flex-wrap gap-6">
              <Stamp tone="verified" size={92}>checked<br />by hand</Stamp>
              <Stamp tone="caution" shape="rect" rotate={6}>risk 57 · medium</Stamp>
            </div>
          </Sheet>
        </section>

        {/* one page sheet with the paper kit */}
        <Sheet className="flex flex-col gap-10 px-5 py-8 sm:px-10">
          <PageHead sheet="Sheet 00 · Styleguide" title="Everything on paper" actions={<Segmented label="View" value={seg} onChange={setSeg} options={[{ id: "files", label: "Files" }, { id: "folders", label: "Folders" }]} />}>
            A page heading set like a map cartouche. Under it, the objects that live on paper.
          </PageHead>

          <div className="grid gap-8 md:grid-cols-4">
            <Figure label="Files" value="124" />
            <Figure label="Symbols" value="807" />
            <Figure label="Import cycles" value="1" risk hint="groups of files that import each other" />
            <Figure label="Median complexity" value="4" />
          </div>

          <div className="grid gap-6 md:grid-cols-3">
            <Card>Box: a ruled box for grouped content.</Card>
            <Card variant="note">Note: a sticky note for the one suggestion on a page.</Card>
            <Card variant="inset">Inset: recessed paper for logs and forms.</Card>
            <Card variant="risk"><span className="font-semibold">Risk</span>: models.py is in an import cycle with utils.py and cookies.py.</Card>
            <Card variant="verified"><span className="font-semibold">Verified</span>: 3 of 3 citations checked against the code.</Card>
            <Card variant="ruled">Ruled: an editorial block with a heavy rule on top.</Card>
          </div>

          <Panel title="A panel is a section, not a box" description="Heavy rule, serif title, content under it." actions={<Button variant="ghost" size="sm">View all</Button>}>
            <Table
              columns={[
                { header: "File", render: (r: { p: string; s: number }) => <span className="font-mono text-small text-ink">{r.p}</span> },
                { header: "Score", render: (r) => <ScoreBar value={r.s} /> },
                { header: "Signals", render: (r) => (r.s > 70 ? <span className="flex gap-1.5"><Badge tone="danger">complex</Badge><Badge>no test</Badge></span> : <Badge>fan-in</Badge>) },
              ]}
              rows={[{ p: "src/requests/models.py", s: 78 }, { p: "src/requests/utils.py", s: 64 }, { p: "src/requests/compat.py", s: 22 }]}
              rowKey={(r) => r.p}
              onRowClick={() => {}}
              isSelected={(r) => r.s === 64}
            />
          </Panel>

          <div className="grid gap-8 md:grid-cols-2">
            <div className="flex flex-col gap-4">
              <div className="mono-label">Progress · ruler</div>
              <ProgressBar value={64} />
              <ProgressBar value={40} failed />
              <div className="mono-label mt-2">Tags</div>
              <div className="flex flex-wrap gap-2"><Badge>neutral</Badge><Badge tone="danger">changed</Badge><Badge tone="warning">medium</Badge><Badge tone="success">verified</Badge><Badge tone="accent">2 hops</Badge></div>
              <div className="mono-label mt-2">Buttons on paper</div>
              <div className="flex flex-wrap items-center gap-3"><Button>Analyse change</Button><Button variant="secondary">Open the code</Button><Button variant="danger">Discard</Button><Button variant="ghost">New chat</Button><Button variant="arrow">Export <Arrow /></Button><Button disabled>Disabled</Button></div>
            </div>
            <div className="flex flex-col gap-4">
              <div className="mono-label">Code</div>
              <CodeBlock code={"def prepare_body(self, data, files, json=None):\n    \"\"\"Prepares the given HTTP body data.\"\"\"\n    body = None"} startLine={498} highlight={["prepare_body"]} />
              <Legend />
            </div>
          </div>

          <div className="grid gap-8 md:grid-cols-2">
            <EmptyState message="Paste a pull request link, a commit SHA or a diff to see what it would break." />
            <div className="flex flex-col gap-2"><Skeleton className="h-5 w-2/3" /><Skeleton className="h-5" /><Skeleton className="h-5 w-5/6" /></div>
          </div>
        </Sheet>
      </main>
    </div>
  );
}
