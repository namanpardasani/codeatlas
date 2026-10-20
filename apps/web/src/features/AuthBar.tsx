import { Button } from "../components/ui";
import { logout, type Me } from "../api";

/** Login state + the scope notice. Public repositories only is stated here and next to the submit box. */
export function AuthBar({ me, onChange }: { me: Me | null; onChange: () => void }) {
  if (!me) return null;
  return (
    <div className="flex flex-wrap items-center gap-gap text-muted">
      {me.user ? (
        <>
          <span>Signed in as {me.user.login}</span>
          <Button
            variant="secondary"
            onClick={async () => {
              await logout();
              onChange();
            }}
          >
            Sign out
          </Button>
        </>
      ) : me.loginAvailable ? (
        <a className="underline" href="/api/auth/github">
          Sign in with GitHub{me.authRequired ? " to analyse a repository" : ""}
        </a>
      ) : me.authRequired ? (
        <span>Login is not configured on this server.</span>
      ) : null}
      {me.demoMode && <span>Read-only demo: explore the pre-analysed repositories.</span>}
    </div>
  );
}
