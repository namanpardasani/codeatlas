import { useEffect, useRef, useState } from "react";
import {
  getFileDetail, getFiles, submitRepo, watchJob,
  type FileDetail, type FileRow, type JobEvent,
} from "./api";
import { SubmitPanel } from "./features/SubmitPanel";
import { JobProgress } from "./features/JobProgress";
import { FilesPanel } from "./features/FilesPanel";
import { FileDetailPanel } from "./features/FileDetailPanel";
import { GraphPanel } from "./features/GraphPanel";

export default function App() {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [job, setJob] = useState<JobEvent | null>(null);
  const [repoId, setRepoId] = useState<string | null>(null);
  const [files, setFiles] = useState<FileRow[]>([]);
  const [selected, setSelected] = useState<string | null>(null);
  const [detail, setDetail] = useState<FileDetail | null>(null);
  const stop = useRef<(() => void) | null>(null);

  useEffect(() => () => stop.current?.(), []);

  async function submit(url: string) {
    setError(null);
    setJob(null);
    setFiles([]);
    setRepoId(null);
    setSelected(null);
    setDetail(null);
    setBusy(true);
    try {
      const { repoId, jobId } = await submitRepo(url);
      stop.current?.();
      stop.current = watchJob(jobId, (e) => {
        setJob(e);
        if (e.status === "done") {
          setRepoId(repoId);
          getFiles(repoId).then(setFiles).catch((err) => setError(String(err.message)));
        }
      });
    } catch (err) {
      setError(err instanceof Error ? err.message : "Something went wrong");
    } finally {
      setBusy(false);
    }
  }

  async function select(f: FileRow) {
    setSelected(f.id);
    try {
      setDetail(await getFileDetail(f.id));
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not load file");
    }
  }

  return (
    <main className="mx-auto flex max-w-5xl flex-col gap-section p-gutter">
      <header>
        <h1 className="text-display font-bold">CodeAtlas</h1>
        <p className="text-muted">Paste a public GitHub repo to analyse its architecture.</p>
      </header>
      <SubmitPanel busy={busy} error={error} onSubmit={submit} />
      {job && <JobProgress job={job} />}
      {repoId && <GraphPanel repoId={repoId} />}
      {files.length > 0 && <FilesPanel files={files} selectedId={selected} onSelect={select} />}
      {detail && <FileDetailPanel detail={detail} />}
    </main>
  );
}
