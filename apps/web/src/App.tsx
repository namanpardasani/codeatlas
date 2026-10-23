import { lazy, Suspense } from "react";
import { BrowserRouter, Route, Routes } from "react-router-dom";
import { Skeleton } from "./components/ui";
import NotFound from "./pages/NotFound";
import Overview from "./pages/Overview";
import Progress from "./pages/Progress";
import RepoLayout from "./pages/RepoLayout";
import SignIn from "./pages/SignIn";

// the map, code viewer, chat and docs are heavy: they load only when their tab is opened
// the landing page is its own chunk, so app screens never download it
const Landing = lazy(() => import("./pages/Landing"));
const MapPage = lazy(() => import("./pages/MapPage"));
const AskPage = lazy(() => import("./pages/AskPage"));
const DocsPage = lazy(() => import("./pages/DocsPage"));
const HotspotsPage = lazy(() => import("./pages/HotspotsPage"));
const BlastPage = lazy(() => import("./pages/BlastPage"));
const ReplayPage = lazy(() => import("./pages/ReplayPage"));
const Styleguide = lazy(() => import("./pages/Styleguide"));

const Fallback = () => <Skeleton className="h-[60vh] w-full rounded-panel" />;
const lazyEl = (el: React.ReactNode) => <Suspense fallback={<Fallback />}>{el}</Suspense>;

export default function App() {
  return (
    <BrowserRouter>
      <Routes>
        <Route path="/" element={<Suspense fallback={<div className="min-h-screen bg-bg" />}><Landing /></Suspense>} />
        <Route path="/analyze/:repoId/:jobId" element={<Progress />} />
        <Route path="/repo/:repoId" element={<RepoLayout />}>
          <Route path="overview" element={<Overview />} />
          <Route path="map" element={lazyEl(<MapPage />)} />
          <Route path="hotspots" element={lazyEl(<HotspotsPage />)} />
          <Route path="blast" element={lazyEl(<BlastPage />)} />
          <Route path="ask" element={lazyEl(<AskPage />)} />
          <Route path="docs" element={lazyEl(<DocsPage />)} />
        </Route>
        <Route path="/signin" element={<SignIn />} />
        <Route path="/replay" element={lazyEl(<ReplayPage />)} />
        {import.meta.env.DEV && <Route path="/styleguide" element={lazyEl(<Styleguide />)} />}
        <Route path="*" element={<NotFound />} />
      </Routes>
    </BrowserRouter>
  );
}
