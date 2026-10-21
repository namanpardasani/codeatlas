import { AnimatePresence, motion } from "framer-motion";
import { useCallback, useEffect, useState } from "react";
import { Navigate, Outlet, useLocation, useNavigate, useParams } from "react-router-dom";
import { reanalyze } from "../api";
import { AppHeader } from "../components/ui";
import { ConnectMcp } from "../features/ConnectMcp";
import { JumpToFile } from "../features/JumpToFile";
import { ago, RepoProvider, useRepo } from "../hooks/RepoData";
import { pageTransition } from "../ui/motion";

const TABS = [
  { id: "overview", label: "Overview" },
  { id: "map", label: "Map" },
  { id: "hotspots", label: "Hotspots" },
  { id: "ask", label: "Ask" },
  { id: "docs", label: "Docs" },
];

function Shell() {
  const { repoId, name, files, runs } = useRepo();
  const navigate = useNavigate();
  const loc = useLocation();
  const [mcp, setMcp] = useState(false);
  const [jump, setJump] = useState(false);
  const tab = loc.pathname.split("/")[3] ?? "overview";
  const last = runs?.find((r) => r.status === "done");

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === "k") {
        e.preventDefault();
        setJump(true);
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  const rerun = useCallback(async () => {
    try {
      const r = await reanalyze(repoId, "auto");
      navigate(`/analyze/${repoId}/${r.jobId}`);
    } catch (e) {
      alert(e instanceof Error ? e.message : "Could not start re-analysis");
    }
  }, [navigate, repoId]);

  // a repository id that has no files and no analyses was never mapped
  if (files && files.length === 0 && runs && runs.length === 0) return <Navigate to="/404" replace />;

  return (
    <div className="min-h-screen bg-bg">
      <AppHeader
        repo={name ?? undefined}
        badge={last ? `${last.commit_sha?.slice(0, 7) ?? "—"} · analyzed ${ago(last.finished_at ?? last.created_at)}` : undefined}
        tabs={TABS}
        active={tab}
        onTab={(id) => navigate(`/repo/${repoId}/${id}`)}
        onReanalyze={rerun}
        onConnect={() => setMcp(true)}
        right={
          <button
            onClick={() => setJump(true)}
            className="hidden min-h-11 items-center gap-3 rounded-ui border border-border bg-surface px-4 text-small text-muted hover:border-border-strong hover:text-text-2 md:inline-flex"
          >
            Jump to file… <kbd className="rounded border border-border-strong px-1.5 font-mono text-micro text-text-3">⌘K</kbd>
          </button>
        }
      />
      <AnimatePresence mode="wait">
        <motion.main key={tab} {...pageTransition} className="mx-auto max-w-7xl px-6 py-8">
          <h1 className="sr-only">{name ?? "Repository"}: {TABS.find((t) => t.id === tab)?.label ?? tab}</h1>
          <Outlet />
        </motion.main>
      </AnimatePresence>
      <ConnectMcp open={mcp} onClose={() => setMcp(false)} />
      <JumpToFile
        open={jump}
        files={files ?? []}
        onClose={() => setJump(false)}
        onPick={(f) => {
          setJump(false);
          navigate(`/repo/${repoId}/map?file=${f.id}`);
        }}
      />
    </div>
  );
}

export default function RepoLayout() {
  const { repoId } = useParams();
  const loc = useLocation();
  if (!repoId || !/^\d+$/.test(repoId)) return <Navigate to="/404" replace />;
  if (loc.pathname === `/repo/${repoId}`) return <Navigate to={`/repo/${repoId}/overview`} replace />;
  return (
    <RepoProvider repoId={repoId}>
      <Shell />
    </RepoProvider>
  );
}
