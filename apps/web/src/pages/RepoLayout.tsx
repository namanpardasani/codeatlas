import { AnimatePresence, motion } from "motion/react";
import { useCallback, useEffect, useState } from "react";
import { Navigate, Outlet, useLocation, useNavigate, useParams } from "react-router-dom";
import { reanalyze } from "../api";
import { AppHeader } from "../components/ui";
import { ConnectMcp } from "../features/ConnectMcp";
import { JumpToFile } from "../features/JumpToFile";
import { ago, RepoProvider, useRepo } from "../hooks/RepoData";


const TABS = [
  { id: "overview", label: "Overview" },
  { id: "map", label: "Map" },
  { id: "blast", label: "Blast Radius" },
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
    <div className="min-h-screen bg-table pb-10">
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
            className="hidden min-h-8 w-56 items-center gap-2 border-b border-table-line px-1 font-mono text-[12px] text-table-muted transition-colors hover:border-table-muted hover:text-table-ink md:inline-flex"
          >
            jump to file… <kbd className="ml-auto font-mono text-[11px] text-table-muted">⌘K</kbd>
          </button>
        }
      />
      {/* the page is one sheet of paper; the open folder tab above is cut from it */}
      <div className="mx-auto max-w-[1360px] px-2 sm:px-6">
        <AnimatePresence mode="wait">
          <motion.main
            key={tab}
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            transition={{ duration: 0.15 }}
            className="sheet min-h-[70vh] rounded-tl-none px-4 py-7 sm:px-8 sm:py-9"
          >
            <span className="sr-only">{name ?? "Repository"}: {TABS.find((t) => t.id === tab)?.label ?? tab}</span>
            <Outlet />
          </motion.main>
        </AnimatePresence>
      </div>
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
