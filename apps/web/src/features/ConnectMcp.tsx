import { Button, MonoLabel } from "../components/ui";
import { Dialog } from "./Dialog";

const CMD = `cd apps/mcp && npm ci
MCP_DB_PASSWORD='<long random>' npx tsx src/admin.ts setup-role   # read-only database role, once
claude mcp add codeatlas -- "$PWD/bin/codeatlas-mcp.sh"`;

/** "Connect MCP": the exact local setup, copied from docs/MCP.md. Read-only tools; nothing is sent anywhere. */
export function ConnectMcp({ open, onClose }: { open: boolean; onClose: () => void }) {
  return (
    <Dialog open={open} title="Connect the MCP server" onClose={onClose}>
      <MonoLabel>MCP SERVER · READ-ONLY</MonoLabel>
      <h2 className="mt-2 text-section">Give Claude Code this map</h2>
      <p className="mt-2 text-small text-text-3">
        Six read-only tools (architecture, symbols, dependencies, hotspots, explain a file, search). Run locally against your database:
      </p>
      <pre className="mt-4 overflow-x-auto rounded-card border border-border bg-code p-4 font-mono text-[12.5px] leading-relaxed text-text-2">{CMD}</pre>
      <div className="mt-5 flex items-center justify-between">
        <a className="text-small text-cyan underline" href="https://github.com/namanpardasani/codeatlas/blob/main/docs/MCP.md" rel="noreferrer">
          Full guide, HTTP keys and threat model
        </a>
        <Button variant="secondary" onClick={onClose}>Close</Button>
      </div>
    </Dialog>
  );
}
