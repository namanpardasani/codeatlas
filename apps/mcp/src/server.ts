import { McpServer } from "@modelcontextprotocol/sdk/server/mcp.js";
import { z } from "zod";
import { REPO_PATTERN, resolveRepo, type Principal, type RepoRef } from "./auth.js";
import { config } from "./config.js";
import type { Db } from "./db.js";
import { CallLimiter } from "./limits.js";
import { fail, text } from "./output.js";
import * as tools from "./tools.js";
import { UserError } from "./tools.js";

export interface Deps {
  db: Db;
  limiter: CallLimiter;
  fetchImpl?: typeof fetch;
}

const repoArg = z
  .string()
  .regex(new RegExp(REPO_PATTERN), "Use owner/name (e.g. psf/requests) or the numeric repo id")
  .describe("Analysed repository as owner/name (e.g. psf/requests) or its numeric id.");
const pathArg = z
  .string()
  .min(1)
  .max(300)
  .refine((s) => !/[\u0000-\u001F\u007F]/.test(s), "Path contains control characters")
  .describe("Path relative to the repository root, e.g. src/requests/models.py. A unique trailing part of the path also works.");
const limit = (def: number, max: number) =>
  z.number().int().min(1).max(max).default(def).describe(`Maximum items to return (1-${max}, default ${def}).`);
const offset = z.number().int().min(0).max(10_000).default(0).describe("Items to skip, for paging. Use next_offset from the previous result.");

const READ_ONLY = { readOnlyHint: true, destructiveHint: false, idempotentHint: true, openWorldHint: false } as const;

// Tool descriptions are constants: they contain no repository data and nothing in the server can change them at
// runtime, so a repository cannot rewrite what a tool claims to do.
export function buildServer(principal: Principal, deps: Deps): McpServer {
  const server = new McpServer({ name: "codeatlas", version: "0.1.0" });

  // Common path for every tool: rate limit -> authorise repo -> run -> bounded, sanitised JSON. Internal errors
  // are logged to stderr (never stdout: that is the stdio protocol channel) and returned without details.
  const guarded =
    <A extends { repo: string }>(name: string, run: (ctx: tools.Ctx, args: A) => Promise<unknown>) =>
    async (args: A) => {
      const slot = deps.limiter.acquire(principal.label);
      if ("error" in slot) return fail(slot.error);
      try {
        const repo: RepoRef | null = await resolveRepo(deps.db, principal, args.repo);
        if (!repo) return fail(`Repository "${args.repo}" was not found, or you have no access to it.`);
        if (repo.status !== "ready") return fail(`${repo.fullName} is not ready (status: ${repo.status}). Try again after the analysis finishes.`);
        const value = await Promise.race([
          run({ db: deps.db, repo, fetchImpl: deps.fetchImpl }, args),
          new Promise<never>((_, rej) => setTimeout(() => rej(new UserError(`${name} timed out.`)), config.toolTimeoutMs).unref()),
        ]);
        return text(value);
      } catch (err) {
        if (err instanceof UserError) return fail(err.message);
        console.error(`[codeatlas-mcp] ${name} failed:`, err instanceof Error ? err.message : err);
        return fail("Internal error while reading analysis data.");
      } finally {
        slot.release();
      }
    };

  server.registerTool(
    "get_architecture",
    {
      title: "Repository architecture overview",
      description:
        "Start here. High-level map of an analysed repository: languages, entry points, how to run it, main modules (folders) " +
        "ranked by importance, dependencies between modules, circular-dependency groups and the most central files. " +
        "Read-only; computed from static analysis, plus a short summary that may be model-written.",
      inputSchema: { repo: repoArg },
      annotations: { ...READ_ONLY, title: "Repository architecture overview" },
    },
    guarded("get_architecture", (ctx) => tools.getArchitecture(ctx)),
  );

  server.registerTool(
    "find_symbol",
    {
      title: "Find a function, class or type",
      description:
        "Find where a function, class, method, interface, type or enum is DEFINED, by name (exact matches first, then " +
        "prefix and substring). Returns file path, line range, signature and whether it is exported. 'Class.method' is accepted. " +
        "Does not find usages; use search_code for that.",
      inputSchema: {
        repo: repoArg,
        name: z
          .string()
          .min(1)
          .max(120)
          .regex(/^[\w$.<>:-]+$/, "Letters, digits, _ $ . < > : - only")
          .describe("Symbol name, e.g. 'prepare_body' or 'Request.prepare_body'."),
        kind: z.enum(["function", "class", "method", "interface", "type", "enum"]).optional().describe("Restrict to one kind."),
        exported_only: z.boolean().optional().describe("Only symbols exported from their file."),
        limit: limit(20, 50),
        offset,
      },
      annotations: { ...READ_ONLY, title: "Find a function, class or type" },
    },
    guarded("find_symbol", (ctx, a: any) => tools.findSymbol(ctx, a)),
  );

  server.registerTool(
    "get_dependencies",
    {
      title: "File dependencies",
      description:
        "Which files a file imports (internal files and external packages), which files import it, and whether it is part of a " +
        "circular-dependency group. Use before changing a file to see what could break. Based on resolved imports.",
      inputSchema: {
        repo: repoArg,
        file: pathArg,
        direction: z.enum(["imports", "imported_by", "both"]).default("both").describe("imports = what this file uses; imported_by = who uses it."),
        limit: limit(30, 100),
        offset,
      },
      annotations: { ...READ_ONLY, title: "File dependencies" },
    },
    guarded("get_dependencies", (ctx, a: any) => tools.getDependencies(ctx, a)),
  );

  server.registerTool(
    "get_hotspots",
    {
      title: "Risky files (hotspots)",
      description:
        "Files that are riskiest to change, ranked by a score combining complexity, change frequency, how many files depend on " +
        "them, dependency cycles, duplication and missing tests, with the reasons. Test files are excluded.",
      inputSchema: { repo: repoArg, limit: limit(10, 30), offset },
      annotations: { ...READ_ONLY, title: "Risky files (hotspots)" },
    },
    guarded("get_hotspots", (ctx, a: any) => tools.getHotspots(ctx, a)),
  );

  server.registerTool(
    "explain_file",
    {
      title: "Explain a file",
      description:
        "What one file is and how it fits in: generated summary (labelled as model-written or extractive), symbols it defines, " +
        "size/complexity/churn metrics, hotspot reasons, what it imports, what imports it, and files usually changed with it. " +
        "Does not return the file's source code.",
      inputSchema: { repo: repoArg, path: pathArg },
      annotations: { ...READ_ONLY, title: "Explain a file" },
    },
    guarded("explain_file", (ctx, a: any) => tools.explainFile(ctx, a)),
  );

  server.registerTool(
    "search_code",
    {
      title: "Search code",
      description:
        "Search the repository's code chunks (functions/classes) by meaning and keywords. Use for 'where is X handled?' questions " +
        "or to find usages. Returns paths, line ranges and short snippets, best first. Up to 20 results per call; refine the query to see others.",
      inputSchema: {
        repo: repoArg,
        query: z.string().trim().min(1).max(300).describe("Natural-language question or identifiers, e.g. 'where are redirects followed'."),
        mode: z.enum(["hybrid", "keyword", "vector"]).default("hybrid").describe("hybrid (default) combines keyword and semantic search."),
        limit: limit(8, 20),
        path_prefix: z.string().max(200).optional().describe("Only files whose path starts with this, e.g. 'src/'."),
        language: z.string().max(40).regex(/^[\w+#-]+$/).optional().describe("Only this language, e.g. 'python'."),
      },
      annotations: { ...READ_ONLY, title: "Search code" },
    },
    guarded("search_code", (ctx, a: any) => tools.searchCode(ctx, a)),
  );

  return server;
}
