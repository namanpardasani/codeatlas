/**
 * The hero map: a hand-set miniature of psf/requests drawn like an atlas plate. File names, the import cycle
 * (models -> cookies -> utils -> models) and the blast of commit 6f66281a are real; positions are composed by hand.
 * Groups carry `data-hop` so the landing's scroll animation can ink them in hop by hop. Decorative for screen readers:
 * the same facts are written out in the worked example below it.
 */
type N = { x: number; y: number; label: string; r: number; hop?: 0 | 1 | 2; dx?: number; dy?: number };
const NODES: Record<string, N> = {
  models: { x: 150, y: 158, label: "models.py", r: 9, hop: 0 },
  types: { x: 82, y: 236, label: "_types.py", r: 6, hop: 0, dx: -6, dy: 18 },
  init: { x: 196, y: 70, label: "__init__.py", r: 6, hop: 1 },
  compat: { x: 378, y: 110, label: "compat.py", r: 8, hop: 1 },
  sessions: { x: 420, y: 222, label: "sessions.py", r: 7, hop: 2 },
  cookies: { x: 222, y: 252, label: "cookies.py", r: 5 },
  utils: { x: 292, y: 176, label: "utils.py", r: 8 },
  api: { x: 300, y: 58, label: "api.py", r: 5 },
  adapters: { x: 452, y: 140, label: "adapters.py", r: 6, dx: -40, dy: 20 },
};
const EDGES: [string, string, ("cycle" | "blast")?][] = [
  ["api", "sessions"], ["sessions", "adapters"], ["sessions", "utils"], ["adapters", "utils"], ["adapters", "compat"],
  ["utils", "compat"], ["init", "models"], ["init", "api"], ["models", "types"],
  ["models", "cookies", "cycle"], ["cookies", "utils", "cycle"], ["utils", "models", "cycle"],
  ["sessions", "models", "blast"],
];

const bend = (a: N, b: N) => {
  const mx = (a.x + b.x) / 2, my = (a.y + b.y) / 2, dx = b.x - a.x, dy = b.y - a.y;
  return `M${a.x} ${a.y} Q${mx - dy * 0.12} ${my + dx * 0.12} ${b.x} ${b.y}`;
};

export function AtlasSheet() {
  return (
    <svg viewBox="0 0 520 330" className="block h-auto w-full" aria-hidden>
      <defs>
        <pattern id="grat" width="52" height="52" patternUnits="userSpaceOnUse">
          <path d="M52 0H0V52" fill="none" stroke="var(--rule)" strokeWidth="0.8" />
        </pattern>
        <marker id="ah" viewBox="0 0 8 8" refX="7" refY="4" markerWidth="6" markerHeight="6" orient="auto"><path d="M0 0 8 4 0 8Z" fill="var(--ink)" opacity=".55" /></marker>
      </defs>
      <rect width="520" height="330" fill="url(#grat)" />
      {/* folder region, outlined in pencil like a survey boundary */}
      <path d="M40 46c70-24 230-30 300-6s170 40 160 120-60 150-180 150S70 330 44 268 0 72 40 46Z" fill="none" stroke="var(--pencil)" strokeWidth="1" strokeDasharray="3 4" opacity=".7" />
      <text x="58" y="70" fontFamily="var(--font-mono)" fontSize="10" letterSpacing="1.6" fill="var(--pencil)">SRC / REQUESTS</text>

      {/* blast rings around the change (hop 1, hop 2) */}
      <g data-hop="1"><circle cx="150" cy="158" r="92" fill="none" stroke="var(--signal)" strokeWidth="1" strokeDasharray="2 4" opacity=".55" /></g>
      <g data-hop="2"><circle cx="150" cy="158" r="270" fill="none" stroke="var(--signal)" strokeWidth="1" strokeDasharray="2 4" opacity=".35" /></g>

      {EDGES.map(([a, b, kind], i) => (
        <path
          key={i}
          d={bend(NODES[a]!, NODES[b]!)}
          fill="none"
          stroke={kind ? "var(--signal)" : "var(--ink)"}
          strokeOpacity={kind ? 1 : 0.45}
          strokeWidth={kind === "blast" ? 1.8 : kind ? 1.6 : 1.1}
          strokeDasharray={kind === "cycle" ? "5 4" : undefined}
          markerEnd={kind ? undefined : "url(#ah)"}
          data-hop={kind === "blast" ? 2 : undefined}
        />
      ))}

      {Object.entries(NODES).map(([k, n]) => {
        const hit = n.hop !== undefined;
        const fill = n.hop === 0 ? "var(--signal)" : hit ? "var(--paper)" : "var(--paper)";
        return (
          <g key={k} data-hop={n.hop}>
            {n.hop === 0 && k === "models" && <circle cx={n.x} cy={n.y} r={n.r + 8} fill="none" stroke="var(--signal)" strokeWidth="1.2" />}
            <circle cx={n.x} cy={n.y} r={n.r} fill={fill} stroke={hit ? "var(--signal)" : "var(--ink)"} strokeWidth={hit && n.hop! > 0 ? 2.2 : 1.4} />
            <text x={n.x + n.r + 6 + (n.dx ?? 0)} y={n.y + 4 + (n.dy ?? 0)} fontFamily="var(--font-mono)" fontSize="11.5" fill={hit ? "var(--signal-ink)" : "var(--ink)"} fontWeight={hit ? 600 : 400} className="map-halo">
              {n.label}
            </text>
          </g>
        );
      })}

      {/* scale bar in hops */}
      <g transform="translate(392 300)" fontFamily="var(--font-mono)" fontSize="9" fill="var(--pencil)">
        <rect width="34" height="5" fill="var(--ink)" /><rect x="34" width="34" height="5" fill="none" stroke="var(--ink)" /><rect x="68" width="34" height="5" fill="var(--ink)" />
        <text y="17">0</text><text x="31" y="17">1</text><text x="65" y="17">2</text><text x="88" y="17">hops</text>
      </g>
    </svg>
  );
}
