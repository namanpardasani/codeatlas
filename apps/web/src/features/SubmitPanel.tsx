import { useState } from "react";
import { Button, Panel } from "../components/ui";

export function SubmitPanel({
  busy,
  error,
  onSubmit,
}: {
  busy: boolean;
  error: string | null;
  onSubmit: (url: string) => void;
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
        <Button disabled={busy || !url.trim()}>{busy ? "Starting…" : "Analyse"}</Button>
      </form>
      {error && <p className="mt-gap text-danger">{error}</p>}
    </Panel>
  );
}
