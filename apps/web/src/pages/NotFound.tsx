import { Link } from "react-router-dom";
import { ButtonLink, Compass, Logo, MarginNote } from "../components/ui";

/**
 * Not found: a torn corner of the map with nothing charted on it. The compass hunts for a heading (the one place a loop
 * says something: we're lost too). One way back.
 */
export default function NotFound() {
  return (
    <main className="flex min-h-screen flex-col bg-table px-4 text-table-ink sm:px-6">
      <header className="mx-auto flex w-full max-w-5xl items-center py-5">
        <Link to="/" aria-label="CodeAtlas home" className="rounded-ui"><Logo /></Link>
      </header>
      <div className="relative mx-auto flex w-full max-w-5xl flex-1 items-center pb-20">
        <div className="absolute right-0 top-[18%] hidden lg:block">
          <MarginNote tone="hl" arrow="down-left" rotate={4}>you are somewhere around here</MarginNote>
        </div>
        <div className="sheet torn tilt relative w-full max-w-2xl px-7 pb-20 pt-9 sm:px-12" style={{ "--tilt": "-1.5deg" } as React.CSSProperties}>
          <div className="bg-graticule pointer-events-none absolute inset-0 opacity-70" aria-hidden />
          <div className="relative">
            <div className="mono-label">Sheet 404 · uncharted</div>
            <h1 className="text-title mt-3 text-ink sm:pr-28">This page isn&apos;t on the map.</h1>
            <p className="mt-4 max-w-md text-[16px] leading-relaxed text-ink-2">
              Either the address is wrong, or that repository was never surveyed. The rest of the atlas is where you left it.
            </p>
            <div className="mt-8 flex flex-wrap items-center gap-5">
              <ButtonLink to="/">Back to the front page</ButtonLink>
              <span className="text-wonk text-[17px] text-pencil">here be no dragons, only a 404</span>
            </div>
            <Compass size={88} mode="hunt" className="absolute -top-2 right-0 hidden text-ink sm:block" title="Compass looking for north" />
          </div>
        </div>
      </div>
    </main>
  );
}
