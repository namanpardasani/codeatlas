import ReactMarkdown from "react-markdown";

/** Markdown with our type scale. Raw HTML is not rendered. Links starting with `doc:` navigate inside the app;
 *  every other link is shown as plain text, so generated content can never send the reader off-site. */
export function Markdown({ children, onNavigate }: { children: string; onNavigate?: (type: "file" | "folder" | "repo", path: string) => void; tone?: string }) {
  return (
    <div className="flex max-w-[68ch] flex-col gap-3 text-[15.5px] leading-[1.75] text-ink-2">
      <ReactMarkdown
        components={{
          h1: (p) => <h1 className="text-title mb-2 text-ink" {...p} />,
          h2: (p) => <h2 className="mt-6 border-t border-rule pt-4 font-display text-[22px] font-semibold tracking-[-0.02em] text-ink" {...p} />,
          h3: (p) => <h3 className="mt-3 font-display text-[17px] font-semibold text-ink" {...p} />,
          p: (p) => <p className="whitespace-pre-wrap" {...p} />,
          ul: (p) => <ul className="list-disc pl-6 marker:text-pencil" {...p} />,
          ol: (p) => <ol className="list-decimal pl-6 marker:text-pencil" {...p} />,
          li: (p) => <li className="py-0.5" {...p} />,
          img: ({ alt }) => <span className="text-pencil">{alt}</span>, // images are never loaded from generated content
          hr: () => <hr className="my-5 border-rule" />,
          blockquote: (p) => <blockquote className="text-wonk border-l-2 border-signal pl-4 text-ink-2" {...p} />,
          em: (p) => <em className="text-ink" {...p} />,
          strong: (p) => <strong className="font-semibold text-ink" {...p} />,
          table: (p) => <div className="overflow-x-auto"><table className="w-full border-collapse text-small" {...p} /></div>,
          th: (p) => <th className="mono-label border-b-2 border-ink px-3 py-2 text-left" {...p} />,
          td: (p) => <td className="border-b border-rule px-3 py-2" {...p} />,
          pre: (p) => <pre className="overflow-x-auto rounded-sm bg-paper-2 p-4 font-mono text-[13px] leading-relaxed text-ink-2 [&_code]:bg-transparent [&_code]:p-0" {...p} />,
          code: ({ className, ...p }) => <code className={`font-mono text-[0.88em] ${className ?? "rounded-sm bg-paper-3 px-1.5 py-0.5 text-ink"}`} {...p} />,
          a: ({ href, children: label }) => {
            const m = /^doc:(file|folder|repo):(.*)$/.exec(href ?? "");
            if (!m || !onNavigate) return <span>{label}</span>;
            return (
              <button className="text-left font-medium text-ink underline decoration-signal decoration-[1.5px] underline-offset-[3px] hover:text-signal-ink" onClick={() => onNavigate(m[1] as "file" | "folder" | "repo", decodeURIComponent(m[2]!))}>
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
