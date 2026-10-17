import { useCallback, useEffect, useState } from "react";

// loads now, again every few seconds (handlers update things asynchronously), and on refresh()
export function usePolled<T>(load: () => Promise<T>, everyMs = 5000): [T | undefined, () => void] {
  const [data, setData] = useState<T>();
  const [tick, setTick] = useState(0);
  const refresh = useCallback(() => setTick((t) => t + 1), []);

  useEffect(() => {
    let live = true;
    const fetchIt = () => load().then((d) => live && setData(d), () => {});
    fetchIt();
    const timer = setInterval(fetchIt, everyMs);
    return () => {
      live = false;
      clearInterval(timer);
    };
  }, [load, everyMs, tick]);

  return [data, refresh];
}
