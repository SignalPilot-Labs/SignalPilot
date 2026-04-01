"use client";

import { useState, useEffect, useCallback } from "react";
import type { Run } from "@/lib/types";
import { fetchRuns } from "@/lib/api";

export function useRuns(pollInterval = 8000) {
  const [runs, setRuns] = useState<Run[]>([]);
  const [loading, setLoading] = useState(true);

  const refresh = useCallback(async () => {
    try {
      const data = await fetchRuns();
      setRuns(data);
    } catch {
      // silently retry on next poll
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    refresh();
    const id = setInterval(refresh, pollInterval);
    return () => clearInterval(id);
  }, [refresh, pollInterval]);

  return { runs, loading, refresh };
}
