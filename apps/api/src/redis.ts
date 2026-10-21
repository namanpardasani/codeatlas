import { Redis } from "ioredis";
import { config } from "./config.js";

// The read-only demo has no Redis: do not connect (and do not spam errors) until something actually needs it.
const opts = { lazyConnect: config.demoMode, maxRetriesPerRequest: config.demoMode ? 1 : 20 };
export const redis = new Redis(config.redisUrl, opts);
redis.on("error", (e) => {
  if (!config.demoMode) console.error("redis:", e.message);
});
export const createSubscriber = () => new Redis(config.redisUrl, { ...opts, lazyConnect: false });
