import type { ReactNode } from "react";

/** Empty: one sentence on what is missing + one action. */
export function EmptyState({ message, action }: { message: string; action?: ReactNode }) {
  return (
    <div className="flex flex-col items-start gap-3 py-6">
      <p className="text-text-3">{message}</p>
      {action}
    </div>
  );
}

/** Error: one sentence on what happened (error colour text only, no red box) + one action. */
export function ErrorState({ message, action }: { message: string; action?: ReactNode }) {
  return (
    <div role="alert" className="flex flex-col items-start gap-3 py-6">
      <p className="text-error">{message}</p>
      {action}
    </div>
  );
}
