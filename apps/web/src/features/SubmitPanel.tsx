import { useState } from "react";
import { Button, Panel } from "../components/ui";

export function SubmitPanel({
  busy,
  error,
  onSubmit,
  disabledReason,
}: {
  busy: boolean;
  error: string | null;
  onSubmit: (url: string) => void;
  /** set when analysis is unavailable (demo mode, login required) */
  disabledReason?: string | null;
}) {
  const [url, setUrl] = useState("");
  return (
    <Panel title="Analyse a repository">
      <form
        className="flex gap-gap"
        onSubmit={(e) => {
          e.preventDefault();
          onSubmit(url);
        }}
      >
        <input
          value={url}
          onChange={(e) => setUrl(e.target.value)}
          placeholder="https://github.com/owner/repo"
          className="flex-1 rounded-ui border border-border bg-surface px-gap py-gap"
        />
        <Button disabled={busy || !url.trim() || Boolean(disabledReason)}>{busy ? "Starting…" : "Analyse"}</Button>
      </form>
      <p className="mt-gap text-muted">Public GitHub repositories only. Private repositories are not supported.</p>
      {disabledReason && <p className="mt-gap text-muted">{disabledReason}</p>}
      {error && <p className="mt-gap text-danger">{error}</p>}
    </Panel>
  );
}
