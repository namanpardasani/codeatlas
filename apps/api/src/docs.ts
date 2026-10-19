// Documentation pages assembled as Markdown from stored summaries (written by the worker) and live data (metrics, graph,
// hotspots). The functions here are pure so they can be unit-tested; the routes in app.ts load the data.

export interface DocsRepo {
  full_name: string;
  docs_status: string | null;
  docs_commit_sha: string | null;
  docs_model: string | null;
  docs_generated_at: string | null;
}
export interface Summary {
  summary: string;
  source: "llm" | "extractive";
  model: string | null;
}
export interface DocFile {
  path: string;
  language: string | null;
  lines: number;
  fan_in: number | null;
  fan_out: number | null;
  pagerank: number | null;
  hotspot_score: number | null;
  hotspot_reasons: { text: string; severity: string }[] | null;
  max_complexity: number | null;
  total_complexity: number | null;
  churn: number | null;
  cycle_idx: number | null;
  has_test: boolean | null;
}
export interface DocSymbol {
  path: string;
  name: string;
  kind: string;
  parent_name: string | null;
  start_line: number;
  end_line: number;
  complexity: number | null;
}
export interface Facts {
  languages?: { language: string; files: number; lines: number }[];
  entry_points?: { path: string; why: string }[];
  run_hints?: { source: string; title: string; commands: string[] }[];
  readme?: { path: string; excerpt: string } | null;
  manifests?: string[];
}
export interface DocsData {
  repo: DocsRepo;
  facts: Facts;
  summaries: Map<string, Summary>;          // key: `${type}:${ref}`
  files: DocFile[];
  symbols: DocSymbol[];
  imports: Map<string, string[]>;           // path -> files it imports
  importedBy: Map<string, string[]>;
  cycles: string[][];                       // groups of file paths
}

/** [text](doc:file:path) links for the in-app viewer; `null` => no links (plain Markdown export). */
export type LinkFor = ((type: "file" | "folder" | "repo", path: string) => string) | null;

export const key = (type: string, ref: string) => `${type}:${ref}`;
const esc = (s: string) => s.replace(/</g, "&lt;");                         // generated text must never inject HTML
const short = (s: string, n = 200) => {
  const m = /^(.+?[.!?])(\s|$)/s.exec(s.replace(/\s+/g, " ").trim());
  return esc((m ? m[1]! : s).slice(0, n));
};
const link = (lf: LinkFor, type: "file" | "folder" | "repo", path: string, label?: string) =>
  lf ? `[\`${label ?? path}\`](${lf(type, path)})` : `\`${label ?? path}\``;

export function footer(repo: DocsRepo): string {
  const when = repo.docs_generated_at ? repo.docs_generated_at.slice(0, 10) : "unknown date";
  const sha = repo.docs_commit_sha ? repo.docs_commit_sha.slice(0, 7) : "unknown commit";
  return [
    "---",
    `*Documentation generated from commit \`${sha}\` on ${when}${repo.docs_model ? ` (model \`${repo.docs_model}\`)` : ""}. ` +
      "Summaries marked *extractive* were assembled from names, docstrings and the import graph without an LLM; every other " +
      "summary was checked against the source it describes. Metrics, hotspots and dependencies are computed from the code.*",
  ].join("\n");
}

function summaryBlock(d: DocsData, type: string, ref: string): string {
  const s = d.summaries.get(key(type, ref));
  if (!s) return "*No summary yet.*";
  return esc(s.summary) + (s.source === "extractive" ? "\n\n*(extractive: assembled without an LLM)*" : "");
}

function fileLines(d: DocsData, paths: string[], lf: LinkFor): string[] {
  return paths.map((p) => `- ${link(lf, "file", p)} — ${short(d.summaries.get(key("file", p))?.summary ?? "")}`);
}

export function renderRepo(d: DocsData, lf: LinkFor): string {
  const out: string[] = [`# ${d.repo.full_name}`, "", summaryBlock(d, "repo", ""), ""];
  const f = d.facts;
  out.push("## At a glance", "");
  if (f.languages?.length)
    out.push("- **Languages:** " + f.languages.slice(0, 5).map((l) => `${l.language} (${l.files} files, ${l.lines.toLocaleString("en-US")} lines)`).join(", "));
  out.push(`- **Files analysed:** ${d.files.length}`);
  const tops = [...new Set(d.files.map((x) => (x.path.includes("/") ? x.path.split("/")[0]! : "")).filter(Boolean))].sort();
  if (tops.length) out.push("- **Top-level folders:** " + tops.map((t) => link(lf, "folder", t, `${t}/`)).join(", "));
  out.push("");
  if (f.entry_points?.length) {
    out.push("## Entry points", "");
    for (const e of f.entry_points) out.push(`- \`${e.path}\` — ${esc(e.why)}`);
    out.push("");
  }
  if (f.run_hints?.length) {
    out.push("## How to run", "", "*Copied literally from the repository's own files.*", "");
    for (const h of f.run_hints.slice(0, 5)) out.push(`**${esc(h.title)}** (\`${h.source}\`)`, "", "```", ...h.commands, "```", "");
  }
  const key_modules = [...d.files].filter((x) => (x.pagerank ?? 0) > 0).sort((a, b) => (b.pagerank ?? 0) - (a.pagerank ?? 0)).slice(0, 6);
  if (key_modules.length) {
    out.push("## Key modules", "", "*Ranked by how many important files depend on them (PageRank over the import graph).*", "");
    out.push(...fileLines(d, key_modules.map((x) => x.path), lf), "");
  }
  out.push("## Risks", "");
  out.push(d.cycles.length
    ? `- **${d.cycles.length} circular dependency group(s).** Largest: ${d.cycles.reduce((a, b) => (b.length > a.length ? b : a)).slice(0, 6).map((p) => `\`${p}\``).join(", ")}${d.cycles.some((c) => c.length > 6) ? ", …" : ""}.`
    : "- No circular dependencies among the analysed files.");
  const hot = [...d.files].filter((x) => x.hotspot_score !== null).sort((a, b) => (b.hotspot_score ?? 0) - (a.hotspot_score ?? 0)).slice(0, 5);
  if (hot.length) {
    out.push("", "### Hotspots", "", "*Complex code that also changes often, depends on many files or lacks tests.*", "");
    for (const h of hot)
      out.push(`- ${link(lf, "file", h.path)} (score ${h.hotspot_score!.toFixed(1)}): ` + esc((h.hotspot_reasons ?? []).slice(0, 2).map((r) => r.text).join("; ")));
  }
  out.push("", footer(d.repo));
  return out.join("\n");
}

export function renderFolder(d: DocsData, folder: string, lf: LinkFor): string {
  const inside = (p: string) => (folder ? p.startsWith(folder + "/") : true);
  const direct = d.files.filter((x) => inside(x.path) && !x.path.slice(folder ? folder.length + 1 : 0).includes("/")).map((x) => x.path).sort();
  const subs = [...new Set(d.files.filter((x) => inside(x.path) && x.path.slice(folder ? folder.length + 1 : 0).includes("/"))
    .map((x) => (folder ? folder + "/" : "") + x.path.slice(folder ? folder.length + 1 : 0).split("/")[0]!))].sort();
  const out = [`# \`${folder}/\``, "", summaryBlock(d, "folder", folder), ""];
  if (subs.length) out.push("## Sub-folders", "", ...subs.map((s) => `- ${link(lf, "folder", s, `${s}/`)} — ${short(d.summaries.get(key("folder", s))?.summary ?? "")}`), "");
  if (direct.length) out.push("## Files", "", ...fileLines(d, direct, lf), "");
  out.push(footer(d.repo));
  return out.join("\n");
}

export function renderFile(d: DocsData, path: string, lf: LinkFor): string {
  const f = d.files.find((x) => x.path === path);
  const out = [`# \`${path}\``, "", summaryBlock(d, "file", path), ""];
  const syms = d.symbols.filter((s) => s.path === path && ["class", "function", "method"].includes(s.kind));
  if (syms.length) {
    out.push("## Defines", "");
    for (const s of syms.slice(0, 40)) {
      const q = s.parent_name ? `${s.parent_name}.${s.name}` : s.name;
      const note = d.summaries.get(key("symbol", `${path}::${q}`));
      out.push(`- \`${q}\` (${s.kind}, lines ${s.start_line}–${s.end_line}${s.complexity ? `, complexity ${s.complexity}` : ""})` + (note ? ` — ${short(note.summary, 260)}` : ""));
    }
    out.push("");
  }
  const imp = d.imports.get(path) ?? [];
  const by = d.importedBy.get(path) ?? [];
  if (imp.length) out.push("## Imports (files in this repo)", "", ...imp.map((p) => `- ${link(lf, "file", p)}`), "");
  if (by.length) out.push("## Used by", "", ...by.slice(0, 20).map((p) => `- ${link(lf, "file", p)}`), ...(by.length > 20 ? [`- … and ${by.length - 20} more`] : []), "");
  if (f) {
    const m = [`${f.lines} lines`];
    if (f.max_complexity !== null) m.push(`max complexity ${f.max_complexity} (total ${f.total_complexity})`);
    if (f.churn !== null) m.push(`${f.churn} commits in the analysis window`);
    if (f.fan_in !== null) m.push(`imported by ${f.fan_in}`);
    if (f.has_test === false) m.push("no matching test file");
    if (f.cycle_idx !== null) m.push("part of a circular dependency group");
    out.push("## Metrics", "", m.join(" · "), "");
    if (f.hotspot_score !== null)
      out.push(`**Hotspot score ${f.hotspot_score.toFixed(1)}.** ` + esc((f.hotspot_reasons ?? []).map((r) => r.text).join("; ")), "");
  }
  out.push(footer(d.repo));
  return out.join("\n");
}

/** Everything in one Markdown file: overview, then every folder, then every file. Plain Markdown, no app links. */
export function renderExport(d: DocsData): string {
  const folders = [...new Set(d.files.flatMap((f) => {
    const parts = f.path.split("/").slice(0, -1);
    return parts.map((_, i) => parts.slice(0, i + 1).join("/"));
  }))].sort();
  const parts = [renderRepo(d, null), ...folders.map((x) => renderFolder(d, x, null)), ...[...d.files].sort((a, b) => a.path.localeCompare(b.path)).map((f) => renderFile(d, f.path, null))];
  return parts.join("\n\n\n");
}

export interface TreeNode {
  type: "folder" | "file";
  path: string;
  name: string;
  summary: string;
  source: string;
  children?: TreeNode[];
}

export function buildTree(d: DocsData): TreeNode[] {
  const root: TreeNode[] = [];
  const folders = new Map<string, TreeNode>();
  const ensure = (path: string): TreeNode[] => {
    if (!path) return root;
    const hit = folders.get(path);
    if (hit) return hit.children!;
    const node: TreeNode = { type: "folder", path, name: path.split("/").pop()!, summary: short(d.summaries.get(key("folder", path))?.summary ?? ""),
                             source: d.summaries.get(key("folder", path))?.source ?? "extractive", children: [] };
    ensure(path.split("/").slice(0, -1).join("/")).push(node);
    folders.set(path, node);
    return node.children!;
  };
  for (const f of [...d.files].sort((a, b) => a.path.localeCompare(b.path))) {
    const parent = f.path.split("/").slice(0, -1).join("/");
    ensure(parent).push({ type: "file", path: f.path, name: f.path.split("/").pop()!, summary: short(d.summaries.get(key("file", f.path))?.summary ?? ""),
                          source: d.summaries.get(key("file", f.path))?.source ?? "extractive" });
  }
  const sort = (nodes: TreeNode[]) => {
    nodes.sort((a, b) => (a.type === b.type ? a.name.localeCompare(b.name) : a.type === "folder" ? -1 : 1));
    nodes.forEach((n) => n.children && sort(n.children));
  };
  sort(root);
  return root;
}
