import { useCallback, useEffect, useState } from "react";
import { getMe, type Me } from "../api";

/** Login state and server limits (GET /me). `null` until loaded or when the API is unreachable. */
export function useMe() {
  const [me, setMe] = useState<Me | null>(null);
  const reload = useCallback(() => {
    getMe().then(setMe).catch(() => setMe(null));
  }, []);
  useEffect(reload, [reload]);
  return { me, reload };
}
