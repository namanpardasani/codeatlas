import Prism from "prismjs";
import "prismjs/components/prism-clike";
import "prismjs/components/prism-javascript";
import "prismjs/components/prism-typescript";
import "prismjs/components/prism-jsx";
import "prismjs/components/prism-tsx";
import "prismjs/components/prism-python";
import "prismjs/components/prism-json";
import "prismjs/components/prism-yaml";
import "prismjs/components/prism-bash";
import "prismjs/components/prism-css";
import "prismjs/components/prism-markdown";
import "prismjs/components/prism-sql";
import "prismjs/components/prism-toml";

export interface Span {
  text: string;
  type?: string;
}

const LANG: Record<string, string> = {
  ts: "typescript", tsx: "tsx", js: "javascript", jsx: "jsx", mjs: "javascript", cjs: "javascript", py: "python", json: "json",
  yml: "yaml", yaml: "yaml", sh: "bash", css: "css", md: "markdown", sql: "sql", toml: "toml", html: "markup",
};

/** Highlight `code` and return one array of spans per line (tokens that cross lines are split, so each line is independent). */
export function highlightLines(code: string, path: string): Span[][] {
  const ext = path.split(".").pop()?.toLowerCase() ?? "";
  const grammar = Prism.languages[LANG[ext] ?? ""];
  const lines: Span[][] = [[]];
  const push = (text: string, type?: string) => {
    const parts = text.split("\n");
    parts.forEach((part, i) => {
      if (i > 0) lines.push([]);
      if (part) lines[lines.length - 1]!.push({ text: part, type });
    });
  };
  if (!grammar) {
    push(code);
    return lines;
  }
  const walk = (t: string | Prism.Token, inherited?: string) => {
    if (typeof t === "string") return push(t, inherited);
    const type = inherited ?? (Array.isArray(t.alias) ? t.alias[0] : t.alias) ?? t.type;
    if (Array.isArray(t.content)) t.content.forEach((c) => walk(c, type));
    else walk(t.content as string | Prism.Token, type);
  };
  Prism.tokenize(code, grammar).forEach((t) => walk(t));
  return lines;
}
