import { Button } from "../components/ui";
import { Dialog } from "./Dialog";

const CMD = `cd apps/mcp && npm ci
MCP_DB_PASSWORD='<long random>' npx tsx src/admin.ts setup-role   # read-only database role, once
claude mcp add codeatlas -- "$PWD/bin/codeatlas-mcp.sh"`;

/** "Connect MCP": the exact local setup, copied from docs/MCP.md. Read-only tools; nothing is sent anywhere. */
export function ConnectMcp({ open, onClose }: { open: boolean; onClose: () => void }) {
  return (
    <Dialog open={open} title="Connect the MCP server" onClose={onClose}>
      <div className="mono-label">MCP · read-only</div>
      <h2 className="text-heading mt-2 text-ink">Give Claude Code this map</h2>
      <p className="mt-2 text-small text-ink-2">
        Six read-only tools (architecture, symbols, dependencies, hotspots, explain a file, search). Run locally against your database:
      </p>
      <pre className="mt-4 overflow-x-auto rounded-sm bg-table p-4 font-mono text-[12.5px] leading-relaxed text-table-ink">{CMD}</pre>
      <div className="mt-5 flex items-center justify-between">
        <a className="text-small font-medium text-ink underline decoration-signal underline-offset-4 hover:text-signal-ink" href="https://github.com/namanpardasani/codeatlas/blob/main/docs/MCP.md" rel="noreferrer">
          Full guide, HTTP keys and threat model
        </a>
        <Button variant="secondary" onClick={onClose}>Close</Button>
      </div>
    </Dialog>
  );
}
