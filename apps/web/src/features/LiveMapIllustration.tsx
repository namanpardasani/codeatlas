/**
 * Hero illustration for the landing page: 6 nodes, curved edges with flowing dashes, pulsing rings on the central (cyan)
 * and hotspot (amber) nodes. Purely decorative (aria-hidden); the panel labels it "illustration".
 */
export function LiveMapIllustration() {
  const nodes = [
    { id: "a", x: 70, y: 70, r: 7 },
    { id: "b", x: 200, y: 40, r: 6 },
    { id: "c", x: 215, y: 150, r: 15, kind: "central" as const },
    { id: "d", x: 90, y: 190, r: 8, kind: "hotspot" as const },
    { id: "e", x: 340, y: 100, r: 7 },
    { id: "f", x: 340, y: 210, r: 6 },
  ];
  const by = Object.fromEntries(nodes.map((n) => [n.id, n]));
  const curve = (a: string, b: string, bend = 28) => {
    const p = by[a]!, q = by[b]!;
    const mx = (p.x + q.x) / 2 + bend, my = (p.y + q.y) / 2 - bend;
    return `M${p.x} ${p.y} Q${mx} ${my} ${q.x} ${q.y}`;
  };
  const edges: { d: string; cls: "plain" | "cycle" | "flow" }[] = [
    { d: curve("a", "c", -20), cls: "plain" },
    { d: curve("b", "c", 18), cls: "flow" },
    { d: curve("e", "c", 24), cls: "flow" },
    { d: curve("f", "c", -22), cls: "plain" },
    { d: curve("c", "d", -26), cls: "cycle" },
    { d: curve("d", "a", 30), cls: "cycle" },
    { d: curve("a", "b", -16), cls: "plain" },
  ];
  return (
    <svg viewBox="0 0 420 260" className="h-full w-full" aria-hidden>
      <defs>
        <marker id="arr" viewBox="0 0 8 8" refX="6" refY="4" markerWidth="6" markerHeight="6" orient="auto">
          <path d="M0 0 L8 4 L0 8 Z" fill="var(--color-faint)" />
        </marker>
      </defs>
      {edges.map((e, i) => (
        <path
          key={i}
          d={e.d}
          fill="none"
          strokeWidth={e.cls === "plain" ? 1.25 : 1.6}
          stroke={e.cls === "cycle" ? "var(--color-amber)" : e.cls === "flow" ? "var(--color-cyan)" : "var(--color-faint)"}
          className={e.cls === "plain" ? "" : "anim-dash"}
          markerEnd={e.cls === "plain" ? "url(#arr)" : undefined}
          opacity={e.cls === "plain" ? 0.8 : 1}
        />
      ))}
      {nodes.map((n) => {
        const color = n.kind === "central" ? "var(--color-cyan)" : n.kind === "hotspot" ? "var(--color-amber)" : "none";
        return (
          <g key={n.id}>
            {n.kind && <circle cx={n.x} cy={n.y} r={n.r} fill="none" stroke={color} strokeWidth="1.5" className="anim-pulse-ring" />}
            <circle cx={n.x} cy={n.y} r={n.r} fill={color} stroke={n.kind ? color : "var(--color-muted)"} strokeWidth="1.5" />
          </g>
        );
      })}
      <g fontFamily="var(--font-mono)" fontSize="9.5">
        <g transform="translate(236 128)">
          <rect width="104" height="18" rx="5" fill="var(--color-cyan-bg)" />
          <text x="8" y="12.5" fill="var(--color-cyan-soft)">central · rank 1</text>
        </g>
        <g transform="translate(112 214)">
          <rect width="104" height="18" rx="5" fill="var(--color-amber-bg)" stroke="var(--color-amber-border)" />
          <text x="8" y="12.5" fill="var(--color-amber-soft)">cycle detected</text>
        </g>
      </g>
    </svg>
  );
}
