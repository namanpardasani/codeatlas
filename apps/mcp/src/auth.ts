import { createHash, randomBytes } from "node:crypto";
import type { Db } from "./db.js";

// ca_ + 32 random bytes (base64url, 43 chars). Only the SHA-256 is stored.
const KEY_RE = /^ca_[A-Za-z0-9_-]{43}$/;

export interface Principal {
  /** null = anonymous (local stdio without a key): public repos only */
  userId: number | null;
  /** stable id for rate limiting and logs; never the key itself */
  label: string;
}

export const ANONYMOUS: Principal = { userId: null, label: "anonymous" };

export const generateKey = () => `ca_${randomBytes(32).toString("base64url")}`;
export const hashKey = (key: string) => createHash("sha256").update(key).digest("hex");

export async function authenticate(db: Db, key: string | undefined): Promise<Principal | null> {
  if (!key || !KEY_RE.test(key)) return null;
  const r = await db.query(
    `SELECT id, user_id FROM api_keys
     WHERE key_hash = $1 AND revoked_at IS NULL AND (expires_at IS NULL OR expires_at > now())`,
    [hashKey(key)],
  );
  const row = r.rows[0];
  return row ? { userId: Number(row.user_id), label: `key:${row.id}` } : null;
}

export interface RepoRef {
  id: number;
  fullName: string;
  status: string;
  commit: string | null;
}

const NAME_RE = /^[A-Za-z0-9_.-]{1,100}\/[A-Za-z0-9_.-]{1,100}$/;
const ID_RE = /^\d{1,12}$/;
export const REPO_PATTERN = "^([A-Za-z0-9_.-]{1,100}/[A-Za-z0-9_.-]{1,100}|\\d{1,12})$";

/**
 * The ONLY way a tool gets a repo id. A repo is visible when it is public or owned by the caller. Unknown and
 * invisible repos are indistinguishable (same answer), so a key cannot probe for private repos.
 */
export async function resolveRepo(db: Db, principal: Principal, ref: string): Promise<RepoRef | null> {
  const byId = ID_RE.test(ref);
  if (!byId && !NAME_RE.test(ref)) return null;
  const r = await db.query(
    `SELECT r.id, r.full_name, r.status,
            (SELECT j.commit_sha FROM analysis_jobs j WHERE j.repo_id = r.id AND j.status = 'done'
             ORDER BY j.id DESC LIMIT 1) AS commit_sha
     FROM repos r
     WHERE ${byId ? "r.id = $1::bigint" : "r.full_name = lower($1)"} AND (r.is_public OR r.owner_id = $2)`,
    [ref, principal.userId],
  );
  const row = r.rows[0];
  return row ? { id: Number(row.id), fullName: row.full_name, status: row.status, commit: row.commit_sha } : null;
}
