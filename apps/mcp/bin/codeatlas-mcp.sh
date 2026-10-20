#!/usr/bin/env bash
# Launcher for the stdio MCP server. Reads the repo's .env (database role, search URL) so no secret has to be
# written into the MCP client's configuration. stdout is the protocol channel: nothing here may print to it.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
if [ -f "$ROOT/.env" ]; then set -a; . "$ROOT/.env"; set +a; fi
cd "$ROOT/apps/mcp"
exec node_modules/.bin/tsx src/stdio.ts
