"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { getJson } from "../../lib/api";

export function useLiveData<T>(path: string, intervalMs = 0) {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [updatedAt, setUpdatedAt] = useState<Date | null>(null);
  const mounted = useRef(true);

  const refresh = useCallback(async () => {
    try {
      const result = await getJson<T>(path);
      if (!mounted.current) return;
      setData(result);
      setError(null);
      setUpdatedAt(new Date());
    } catch (cause) {
      if (!mounted.current) return;
      setError(cause instanceof Error ? cause.message : "Unable to load current state");
    } finally {
      if (mounted.current) setLoading(false);
    }
  }, [path]);

  useEffect(() => {
    mounted.current = true;
    void refresh();
    const timer = intervalMs > 0 ? window.setInterval(() => void refresh(), intervalMs) : undefined;
    return () => {
      mounted.current = false;
      if (timer) window.clearInterval(timer);
    };
  }, [intervalMs, refresh]);

  return { data, error, loading, updatedAt, refresh };
}
