import { createContext, useContext, useEffect, useMemo, useState, type ReactNode } from "react";
import {
  getAnalyses, getDocsTree, getFileGraphOverview, getFiles, getHotspots,
  type AnalysisRun, type FileGraphNode, type FileRow, type GraphResponse, type HotspotsResponse,
} from "../api";

export interface RepoData {
  repoId: string;
  name: string | null;
  files: FileRow[] | null;
  hotspots: HotspotsResponse | null;
  graph: GraphResponse<FileGraphNode> | null;
  runs: AnalysisRun[] | null;
  error: string | null;
  reload: () => void;
}

const Ctx = createContext<RepoData | null>(null);
export const useRepo = () => {
  const v = useContext(Ctx);
  if (!v) throw new Error("useRepo outside RepoProvider");
  return v;
};

/** One fetch of everything the repo tabs share (existing endpoints only), so tabs open instantly and agree with each other. */
export function RepoProvider({ repoId, children }: { repoId: string; children: ReactNode }) {
  const [state, setState] = useState<Omit<RepoData, "repoId" | "reload">>({ name: null, files: null, hotspots: null, graph: null, runs: null, error: null });
  const [tick, setTick] = useState(0);
  useEffect(() => {
    let stop = false;
    setState({ name: null, files: null, hotspots: null, graph: null, runs: null, error: null });
    const set = (p: Partial<typeof state>) => !stop && setState((s) => ({ ...s, ...p }));
    getFiles(repoId).then((files) => set({ files })).catch((e) => set({ error: e instanceof Error ? e.message : "Could not load repository" }));
    getHotspots(repoId, "score", "desc").then((hotspots) => set({ hotspots })).catch(() => set({ hotspots: null }));
    getFileGraphOverview(repoId, 1000).then((graph) => set({ graph })).catch(() => set({ graph: null }));
    getAnalyses(repoId).then((runs) => set({ runs })).catch(() => set({ runs: [] }));
    getDocsTree(repoId).then((t) => set({ name: t.name })).catch(() => set({ name: null }));
    return () => {
      stop = true;
    };
  }, [repoId, tick]);
  const value = useMemo(() => ({ repoId, ...state, reload: () => setTick((t) => t + 1) }), [repoId, state]);
  return <Ctx.Provider value={value}>{children}</Ctx.Provider>;
}

export const basename = (p: string) => p.split("/").pop() ?? p;
export const ago = (iso: string | null | undefined): string => {
  if (!iso) return "—";
  const s = Math.max(0, (Date.now() - new Date(iso).getTime()) / 1000);
  if (s < 90) return "just now";
  if (s < 5400) return `${Math.round(s / 60)} min ago`;
  if (s < 129600) return `${Math.round(s / 3600)} h ago`;
  return `${Math.round(s / 86400)} d ago`;
};
