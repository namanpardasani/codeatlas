import { Link } from "react-router-dom";
import { Logo, NorthMark } from "../components/ui";

/** Not-found, in the atlas voice. */
export default function NotFound() {
  return (
    <main className="bg-dot-grid flex min-h-screen flex-col items-center justify-center gap-6 px-6 text-center">
      <Logo />
      <NorthMark size={44} />
      <h1 className="text-page">This region isn&apos;t on the map.</h1>
      <p className="max-w-md text-text-3">The page you asked for doesn&apos;t exist, or the repository was never mapped.</p>
      <Link to="/" className="inline-flex min-h-11 items-center rounded-ui border border-cyan bg-cyan px-6 font-bold text-cyan-ink hover:-translate-y-px">Back to the map</Link>
    </main>
  );
}
