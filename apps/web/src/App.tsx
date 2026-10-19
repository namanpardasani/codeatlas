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
import { HotspotsPanel } from "./features/HotspotsPanel";
import { SearchPanel } from "./features/SearchPanel";
import { ChatPanel } from "./features/ChatPanel";
import { ReanalyzePanel } from "./features/ReanalyzePanel";
import { DocsPanel } from "./features/DocsPanel";
import { CodeViewer, type ViewerTarget } from "./features/CodeViewer";
import { FileMetricsPanel } from "./features/FileMetricsPanel";

export default function App() {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [job, setJob] = useState<JobEvent | null>(null);
  const [repoId, setRepoId] = useState<string | null>(null);
  const [files, setFiles] = useState<FileRow[]>([]);
  const [selected, setSelected] = useState<string | null>(null);
  const [detail, setDetail] = useState<FileDetail | null>(null);
  const [viewer, setViewer] = useState<ViewerTarget | null>(null);
  const [refreshKey, setRefreshKey] = useState(0);
  const stop = useRef<(() => void) | null>(null);

  useEffect(() => () => stop.current?.(), []);

  async function submit(url: string) {
    setError(null);
    setJob(null);
    setFiles([]);
    setRepoId(null);
    setSelected(null);
    setDetail(null);
    setViewer(null);
    setBusy(true);
    try {
      const { repoId, jobId } = await submitRepo(url);
      follow(repoId, jobId);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Something went wrong");
    } finally {
      setBusy(false);
    }
  }

  /** Watch a job; when it finishes, reload everything that depends on the analysis. */
  function follow(repo: string, jobId: string) {
    setRepoId(repo);
    stop.current?.();
    stop.current = watchJob(jobId, (e) => {
      setJob(e);
      if (e.status === "done") {
        getFiles(repo).then(setFiles).catch((err) => setError(String(err.message)));
        setRefreshKey((k) => k + 1);
      }
    });
  }

  async function selectId(id: string) {
    setSelected(id);
    try {
      setDetail(await getFileDetail(id));
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
      {repoId && (
        <ReanalyzePanel
          repoId={repoId}
          busy={job !== null && job.status !== "done" && job.status !== "failed"}
          refreshKey={refreshKey}
          onStart={(jobId) => { setJob(null); follow(repoId, jobId); }}
        />
      )}
      {repoId && <DocsPanel repoId={repoId} refreshKey={refreshKey} />}
      {repoId && <ChatPanel repoId={repoId} onOpen={setViewer} />}
      {repoId && viewer && <CodeViewer repoId={repoId} target={viewer} onClose={() => setViewer(null)} />}
      {repoId && <SearchPanel repoId={repoId} onOpen={setViewer} />}
      {repoId && <HotspotsPanel key={refreshKey} repoId={repoId} selectedId={selected} onSelect={selectId} />}
      {selected && <FileMetricsPanel fileId={selected} />}
      {repoId && <GraphPanel key={refreshKey} repoId={repoId} />}
      {files.length > 0 && <FilesPanel files={files} selectedId={selected} onSelect={(f) => selectId(f.id)} />}
      {detail && <FileDetailPanel detail={detail} />}
    </main>
  );
}
