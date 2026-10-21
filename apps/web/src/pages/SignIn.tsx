import { Link } from "react-router-dom";
import { Logo } from "../components/ui";
import { useMe } from "../hooks/useMe";

/** Sign-in: the logo, one line, one button. Only public profile data is read; no GitHub token is stored. */
export default function SignIn() {
  const { me } = useMe();
  return (
    <main className="bg-dot-grid flex min-h-screen flex-col items-center justify-center gap-6 px-6 text-center">
      <Logo />
      <h1 className="text-page">Sign in to map a repository.</h1>
      <p className="max-w-md text-text-3">We read your public GitHub profile to count your analyses. Nothing else, and no token is stored.</p>
      {me?.loginAvailable ? (
        <a href="/api/auth/github" className="inline-flex min-h-11 items-center rounded-ui border border-cyan bg-cyan px-6 font-bold text-cyan-ink hover:-translate-y-px">Sign in with GitHub</a>
      ) : (
        <p className="text-small text-muted">Login is not configured on this server.</p>
      )}
      <Link to="/" className="text-small text-muted underline hover:text-text">Back home</Link>
    </main>
  );
}
