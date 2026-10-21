import ReactMarkdown from "react-markdown";

/** Markdown with our type scale. Raw HTML is not rendered. Links starting with `doc:` navigate inside the app;
 *  every other link is shown as plain text, so generated content can never send the reader off-site. */
export function Markdown({ children, onNavigate }: { children: string; onNavigate?: (type: "file" | "folder" | "repo", path: string) => void }) {
  return (
    <div className="flex flex-col gap-3 text-[15px] leading-[1.7] text-text-2">
      <ReactMarkdown
        components={{
          h1: (p) => <h1 className="text-section mb-1 text-text" {...p} />,
          h2: (p) => <h2 className="mt-4 font-display text-[17px] font-semibold text-text" {...p} />,
          h3: (p) => <h3 className="mt-2 font-semibold text-text" {...p} />,
          p: (p) => <p className="whitespace-pre-wrap" {...p} />,
          ul: (p) => <ul className="list-disc pl-6 marker:text-faint" {...p} />,
          ol: (p) => <ol className="list-decimal pl-6 marker:text-faint" {...p} />,
          li: (p) => <li className="py-0.5" {...p} />,
          img: ({ alt }) => <span className="text-muted">{alt}</span>,   // images are never loaded from generated content
          hr: () => <hr className="my-4 border-line" />,
          blockquote: (p) => <blockquote className="border-l-2 border-border-strong pl-4 text-muted" {...p} />,
          em: (p) => <em className="text-text-3" {...p} />,
          strong: (p) => <strong className="font-semibold text-text" {...p} />,
          table: (p) => <div className="overflow-x-auto"><table className="w-full border-collapse text-small" {...p} /></div>,
          th: (p) => <th className="border-b border-line px-3 py-2 text-left text-[12px] font-medium text-muted" {...p} />,
          td: (p) => <td className="border-b border-line px-3 py-2" {...p} />,
          pre: (p) => <pre className="overflow-x-auto rounded-card border border-border bg-code p-4 font-mono text-[13px] leading-relaxed text-text-2" {...p} />,
          code: ({ className, ...p }) => (
            <code className={`font-mono text-[0.9em] ${className ?? ""} ${className ? "" : "rounded bg-surface-2 px-1.5 py-0.5 text-cyan-soft"}`} {...p} />
          ),
          a: ({ href, children: label }) => {
            const m = /^doc:(file|folder|repo):(.*)$/.exec(href ?? "");
            if (!m || !onNavigate) return <span>{label}</span>;
            return (
              <button className="text-left text-cyan-soft underline decoration-cyan-bg underline-offset-2 hover:decoration-cyan" onClick={() => onNavigate(m[1] as "file" | "folder" | "repo", decodeURIComponent(m[2]!))}>
                {label}
              </button>
            );
          },
        }}
        // react-markdown drops unknown URL schemes by default; allow ours through so doc: links reach the `a` renderer
        urlTransform={(url) => (url.startsWith("doc:") ? url : "")}
      >
        {children}
      </ReactMarkdown>
    </div>
  );
}
