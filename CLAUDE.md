# CodeAtlas

Full context, scope, pipeline, stack, data model, eval plan and timeline: see [PROJECT_BRIEF.md](PROJECT_BRIEF.md). Read it at the start of every session.

## CURRENT MODE (set by user on 2026-10-16, overrides the rules below)

Build mode: keep building phase after phase without teaching, quizzing, or asking the user to write section-9 parts. The user will learn at the end. Commit in small steps and push to GitHub as work progresses (user explicitly authorized commits and pushes). Still flag security/cost issues, keep NOTES.md updated, and keep notes detailed enough for the user to study later.

## UI RULE (standing, set 2026-10-16)

Build functional, clean but minimal/unstyled screens. NO visual polish yet. ALL styling is centralized: Tailwind v4 theme tokens (`@theme` in `apps/web/src/index.css`: colors, spacing, typography, radius) plus small reusable components in `apps/web/src/components/ui/` (Button, Card, Badge, Panel, Table). Pages use only semantic token classes (e.g. `bg-surface text-fg`), never raw palette colors, so a full redesign = change tokens + components, not pages.

Design handoff: when it is time to design how the site looks, tell the user; they will send the designs. Do not invent a visual design.

## Working rules (brief section 13) — original, superseded by the mode above where they conflict

- Teach first, then build: explain the concept simply, show where each tool fits and why, then plan, then code.
- One small, commit-sized step at a time. Never dump the whole app.
- For the parts in brief section 9 (dependency graph + cycles, hotspot formula, AST-aware chunking, eval harness, optional import resolver), ask the user to write them first, then review. Do not write them first.
- After each major piece, quiz the user with 3-5 interview-style questions and correct gaps.
- Be honest: push back on overkill, flag cost / free-tier risks, verify current library versions and limits instead of guessing.
- Flag security issues proactively (SSRF, malicious repos, token handling, prompt injection via repo contents).
- Keep explanations simple and concrete; the user is still learning Python, graphs, vector search and MCP.
- When the user pastes errors, explain the cause, not only the fix.
- Budget is zero: prefer free tiers / local models (Ollama); tell the user before anything could cost money.
- Commit/push: originally only on request; now authorized (see CURRENT MODE).
- Phases start on user's prompt/"go"; in build mode, continue to the next phase automatically.

## End of every session

Update [NOTES.md](NOTES.md): architecture, decisions and tradeoffs, "what happens if X fails" answers, interview Q&A, and the progress log.
