import type { ReactNode } from "react";

/** Empty: one honest sentence, in the italic margin voice, plus one action. */
export function EmptyState({ message, action }: { message: string; action?: ReactNode }) {
  return (
    <div className="flex flex-col items-start gap-4 py-6">
      <p className="text-wonk max-w-xl text-[19px] leading-snug text-pencil">{message}</p>
      {action}
    </div>
  );
}

/** Error: one sentence on what happened in red ink (no red box) plus one action. */
export function ErrorState({ message, action }: { message: string; action?: ReactNode }) {
  return (
    <div role="alert" className="flex flex-col items-start gap-3 py-6">
      <p className="text-signal-ink"><span className="mono-label mr-2 text-signal-ink">Error</span>{message}</p>
      {action}
    </div>
  );
}
