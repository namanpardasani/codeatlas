// Operator CLI. Uses the OWNER database role (DATABASE_URL); the MCP server itself never does.
//   npm run admin -- setup-role            create/refresh the read-only role codeatlas_mcp (password from MCP_DB_PASSWORD)
//   npm run admin -- create-key <email> [name] [days]
//   npm run admin -- list-keys
//   npm run admin -- revoke-key <id>
//   npm run admin -- set-public <owner/name> <true|false>
import pg from "pg";
import { generateKey, hashKey } from "./auth.js";
import { config } from "./config.js";

// Everything the tools read, and nothing else (no chat history, no LLM usage, no cached embeddings).
export const READABLE_TABLES = [
  "repos", "analysis_jobs", "files", "symbols", "imports_raw", "dependencies", "dependency_cycles", "module_edges",
  "file_cochange", "duplicate_groups", "duplicate_blocks", "chunks", "doc_summaries", "repo_facts", "api_keys",
];

export async function setupRole(client: pg.Client, password: string) {
  const lit = client.escapeLiteral(password);
  const exists = await client.query("SELECT 1 FROM pg_roles WHERE rolname = 'codeatlas_mcp'");
  await client.query(
    `${exists.rowCount ? "ALTER" : "CREATE"} ROLE codeatlas_mcp LOGIN PASSWORD ${lit} NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION CONNECTION LIMIT 20`,
  );
  await client.query("ALTER ROLE codeatlas_mcp SET default_transaction_read_only = on");
  await client.query("ALTER ROLE codeatlas_mcp SET statement_timeout = '8s'");
  const db = (await client.query("SELECT current_database() AS d")).rows[0].d;
  await client.query(`REVOKE ALL ON DATABASE ${client.escapeIdentifier(db)} FROM PUBLIC`);
  await client.query(`GRANT CONNECT ON DATABASE ${client.escapeIdentifier(db)} TO codeatlas_mcp`);
  await client.query("GRANT USAGE ON SCHEMA public TO codeatlas_mcp");
  await client.query("REVOKE ALL ON ALL TABLES IN SCHEMA public FROM codeatlas_mcp");
  await client.query(`GRANT SELECT ON ${READABLE_TABLES.join(", ")} TO codeatlas_mcp`);
  // api_keys: the server may look up a hash, but never needs to read the other columns' users; column-level grant.
  await client.query("REVOKE SELECT ON api_keys FROM codeatlas_mcp");
  await client.query("GRANT SELECT (id, user_id, key_hash, revoked_at, expires_at) ON api_keys TO codeatlas_mcp");
}

async function main() {
  const [cmd, ...args] = process.argv.slice(2);
  const client = new pg.Client({ connectionString: config.adminDatabaseUrl });
  await client.connect();
  try {
    if (cmd === "setup-role") {
      const pw = process.env.MCP_DB_PASSWORD;
      if (!pw || pw === "change-me-mcp" || pw.length < 12) throw new Error("Set MCP_DB_PASSWORD to a strong password (12+ chars, not the default).");
      await setupRole(client, pw);
      console.log("role codeatlas_mcp ready (read-only). Use MCP_DATABASE_URL=postgres://codeatlas_mcp:<password>@127.0.0.1:<port>/<db>");
    } else if (cmd === "create-key") {
      const [email, name = "key", days] = args;
      if (!email?.includes("@")) throw new Error("usage: create-key <email> [name] [days]");
      const u = await client.query(
        "INSERT INTO users (email) VALUES ($1) ON CONFLICT (email) DO UPDATE SET email = EXCLUDED.email RETURNING id",
        [email.toLowerCase()],
      );
      const key = generateKey();
      await client.query(
        `INSERT INTO api_keys (user_id, name, key_hash, key_prefix, expires_at)
         VALUES ($1, $2, $3, $4, CASE WHEN $5::int IS NULL THEN NULL ELSE now() + make_interval(days => $5::int) END)`,
        [u.rows[0].id, name.slice(0, 80), hashKey(key), key.slice(0, 7), days ? Number(days) : null],
      );
      console.log(`API key (shown once, store it safely):\n${key}`);
    } else if (cmd === "list-keys") {
      const r = await client.query(
        `SELECT k.id, u.email, k.name, k.key_prefix || '…' AS key, k.created_at, k.expires_at, k.revoked_at
         FROM api_keys k JOIN users u ON u.id = k.user_id ORDER BY k.id`,
      );
      console.table(r.rows);
    } else if (cmd === "revoke-key") {
      const r = await client.query("UPDATE api_keys SET revoked_at = now() WHERE id = $1 AND revoked_at IS NULL", [Number(args[0])]);
      console.log(r.rowCount ? "revoked" : "no such active key");
    } else if (cmd === "set-public") {
      const [name, flag] = args;
      const r = await client.query("UPDATE repos SET is_public = $2 WHERE full_name = lower($1)", [name, flag === "true"]);
      console.log(r.rowCount ? "updated" : "no such repo");
    } else {
      console.log("commands: setup-role | create-key <email> [name] [days] | list-keys | revoke-key <id> | set-public <owner/name> <true|false>");
    }
  } finally {
    await client.end();
  }
}

if (process.argv[1] && import.meta.url.endsWith(process.argv[1].split("/").pop()!)) {
  main().catch((e) => {
    console.error(e instanceof Error ? e.message : e);
    process.exit(1);
  });
}
