import { Link } from "react-router-dom";
import { Arrow, ButtonAnchor, Icon, Logo, Sheet } from "../components/ui";
import { useMe } from "../hooks/useMe";

/** Sign-in: a library card on the table. Only public profile data is read; no GitHub token is stored. */
export default function SignIn() {
  const { me } = useMe();
  return (
    <main className="flex min-h-screen flex-col bg-table px-4 text-table-ink sm:px-6">
      <header className="mx-auto flex w-full max-w-5xl items-center py-5">
        <Link to="/" aria-label="CodeAtlas home" className="rounded-ui"><Logo /></Link>
      </header>
      <div className="mx-auto grid w-full max-w-5xl flex-1 grid-cols-[minmax(0,1fr)] items-center gap-12 pb-20 md:grid-cols-[1fr_420px]">
        <div>
          <p className="mono-label text-table-muted">Reader&apos;s card</p>
          <h1 className="mt-4 font-display text-[clamp(34px,5vw,56px)] font-semibold leading-[0.98] tracking-[-0.04em]">Sign in to survey a new repository.</h1>
          <p className="mt-5 max-w-md text-[16px] leading-relaxed text-table-muted">Browsing the repositories already mapped needs no account. Mapping a new one does, so the free tier can stay free.</p>
        </div>
        <Sheet tilt={1.2} className="p-7">
          <div className="flex items-baseline justify-between border-b-[1.5px] border-ink pb-2">
            <span className="font-display text-[20px] font-semibold">CodeAtlas reader</span>
            <span className="font-mono text-[10.5px] uppercase tracking-[0.12em] text-pencil">no. ____</span>
          </div>
          <dl className="mt-4 flex flex-col gap-3 text-[14px]">
            <div><dt className="mono-label">We read</dt><dd className="mt-0.5 text-ink-2">your public GitHub profile, to count your analyses</dd></div>
            <div><dt className="mono-label">We store</dt><dd className="mt-0.5 text-ink-2">no token, nothing else</dd></div>
          </dl>
          {me?.loginAvailable ? (
            <ButtonAnchor href="/api/auth/github" size="lg" className="mt-6 w-full"><Icon name="github" size={18} /> Continue with GitHub</ButtonAnchor>
          ) : (
            <p className="text-wonk mt-6 border-t border-rule pt-4 text-[16px] text-pencil">Sign-in isn&apos;t configured on this server, so this copy is read-only.</p>
          )}
        </Sheet>
      </div>
      <Link to="/" className="group mx-auto mb-8 inline-flex items-center gap-2 font-mono text-[11.5px] uppercase tracking-[0.12em] text-table-muted hover:text-table-ink"><Arrow dir="left" /> Back to the front page</Link>
    </main>
  );
}
