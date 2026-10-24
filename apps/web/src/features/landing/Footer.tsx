export const GITHUB = "https://github.com/namanpardasani/codeatlas";

const LINKS: [string, string][] = [
  ["Source", GITHUB],
  ["Evaluation", `${GITHUB}/blob/main/docs/BLAST_RADIUS_EVAL.md`],
  ["Security", `${GITHUB}/blob/main/docs/SECURITY.md`],
  ["MCP guide", `${GITHUB}/blob/main/docs/MCP.md`],
  ["Deploy your own", `${GITHUB}/blob/main/docs/DEPLOYMENT.md`],
];

/** The colophon: one line at the bottom of the table, like the imprint of a printed atlas. */
export function Colophon() {
  return (
    <footer className="border-t border-table-line">
      <div className="mx-auto flex max-w-[1240px] 2xl:max-w-[1440px] flex-wrap items-baseline justify-between gap-x-8 gap-y-3 px-4 py-8 sm:px-6">
        <p className="text-wonk text-[15px] text-table-muted">
          CodeAtlas. Open source, set in Fraunces and IBM Plex. Code is read, never run.
        </p>
        <nav aria-label="Project" className="flex flex-wrap gap-x-5 gap-y-2 font-mono text-[11.5px] uppercase tracking-[0.1em]">
          {LINKS.map(([label, href]) => (
            <a key={label} href={href} className="text-table-muted transition-colors hover:text-table-ink">{label}</a>
          ))}
        </nav>
      </div>
    </footer>
  );
}
