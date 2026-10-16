// Strict allowlist for repo URLs. Only https://github.com/<owner>/<repo> is accepted.
// This is the SSRF / git-option-injection defence: the worker never sees any other host.
const OWNER = /^[A-Za-z0-9](?:[A-Za-z0-9-]{0,38})$/;
const REPO = /^[A-Za-z0-9._-]{1,100}$/;

export interface ParsedRepo {
  url: string; // canonical clone URL
  owner: string;
  name: string;
  fullName: string; // lowercased "owner/name"
}

export function parseGithubUrl(input: string): ParsedRepo | null {
  if (typeof input !== "string" || input.length > 200) return null;
  let u: URL;
  try {
    u = new URL(input.trim());
  } catch {
    return null;
  }
  if (u.protocol !== "https:") return null;
  if (u.hostname !== "github.com") return null;
  if (u.username || u.password || u.port || u.search || u.hash) return null;

  const parts = u.pathname.split("/").filter(Boolean);
  if (parts.length !== 2) return null;
  const owner = parts[0]!;
  let name = parts[1]!;
  if (name.endsWith(".git")) name = name.slice(0, -4);
  if (!OWNER.test(owner) || !REPO.test(name)) return null;
  if (name === "." || name === ".." || name.startsWith("-")) return null;

  return {
    url: `https://github.com/${owner}/${name}`,
    owner,
    name,
    fullName: `${owner}/${name}`.toLowerCase(),
  };
}
