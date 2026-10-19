import ReactMarkdown from "react-markdown";

/** Markdown with theme-token styling. Raw HTML is not rendered. Links starting with `doc:` navigate inside the app;
 *  every other link is shown as plain text, so generated content can never send the reader off-site. */
export function Markdown({ children, onNavigate }: { children: string; onNavigate?: (type: "file" | "folder" | "repo", path: string) => void }) {
  return (
    <div className="flex flex-col gap-gap">
      <ReactMarkdown
        components={{
          h1: (p) => <h1 className="mb-gap text-title font-bold" {...p} />,
          h2: (p) => <h2 className="mt-gutter text-body font-bold" {...p} />,
          h3: (p) => <h3 className="mt-gap font-semibold" {...p} />,
          p: (p) => <p className="whitespace-pre-wrap" {...p} />,
          ul: (p) => <ul className="list-disc pl-section" {...p} />,
          ol: (p) => <ol className="list-decimal pl-section" {...p} />,
          hr: () => <hr className="my-gutter border-border" />,
          blockquote: (p) => <blockquote className="border-l-2 border-border pl-gutter text-muted" {...p} />,
          em: (p) => <em className="text-muted" {...p} />,
          pre: (p) => <pre className="overflow-x-auto rounded-ui border border-border bg-bg p-gap font-mono text-small" {...p} />,
          code: ({ className, ...p }) => <code className={`font-mono text-small ${className ?? ""}`} {...p} />,
          a: ({ href, children: label }) => {
            const m = /^doc:(file|folder|repo):(.*)$/.exec(href ?? "");
            if (!m || !onNavigate) return <span>{label}</span>;
            return (
              <button className="text-left text-info" onClick={() => onNavigate(m[1] as "file" | "folder" | "repo", decodeURIComponent(m[2]!))}>
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
