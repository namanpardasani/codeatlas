// Per-principal limits: a sliding one-minute window of calls plus a cap on calls in flight.
export class CallLimiter {
  private hits = new Map<string, number[]>();
  private inflight = new Map<string, number>();

  constructor(private perMinute: number, private maxConcurrent: number, private now: () => number = Date.now) {}

  /** Returns a release function, or an error message when the caller must back off. */
  acquire(who: string): { release: () => void } | { error: string } {
    const t = this.now();
    const recent = (this.hits.get(who) ?? []).filter((x) => t - x < 60_000);
    if (recent.length >= this.perMinute) {
      const wait = Math.max(1, Math.ceil((60_000 - (t - recent[0]!)) / 1000));
      this.hits.set(who, recent);
      return { error: `Rate limit reached (${this.perMinute} calls/minute). Retry in ${wait}s.` };
    }
    const busy = this.inflight.get(who) ?? 0;
    if (busy >= this.maxConcurrent) {
      this.hits.set(who, recent);
      return { error: `Too many calls in flight (max ${this.maxConcurrent}). Wait for one to finish.` };
    }
    recent.push(t);
    this.hits.set(who, recent);
    this.inflight.set(who, busy + 1);
    let released = false;
    return {
      release: () => {
        if (released) return;
        released = true;
        this.inflight.set(who, (this.inflight.get(who) ?? 1) - 1);
      },
    };
  }
}
