import pg from "pg";
import { config } from "./config.js";

export type Db = Pick<pg.Pool, "query">;

// Defence in depth on top of the read-only role: every session is read-only and time-limited.
export function createPool(url = config.databaseUrl): pg.Pool {
  return new pg.Pool({
    connectionString: url,
    max: 6,
    options: "-c default_transaction_read_only=on -c statement_timeout=8000 -c idle_in_transaction_session_timeout=10000",
  });
}
