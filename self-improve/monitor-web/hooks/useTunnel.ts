"use client";

import { useState, useEffect, useCallback, useRef } from "react";
import {
  fetchTunnelStatus,
  startTunnel as apiStart,
  stopTunnel as apiStop,
} from "@/lib/api";
import type { TunnelStatus } from "@/lib/api";

const POLL_INTERVAL = 10_000;
const RAPID_POLLS = [1000, 3000, 5000];

export function useTunnel() {
  const [status, setStatus] = useState<TunnelStatus["status"]>("not_found");
  const [url, setUrl] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const rapidTimers = useRef<ReturnType<typeof setTimeout>[]>([]);

  const refresh = useCallback(async () => {
    const data = await fetchTunnelStatus();
    setStatus(data.status);
    setUrl(data.url);
  }, []);

  // Rapid-poll after an action to catch URL propagation
  const rapidRefresh = useCallback(() => {
    rapidTimers.current.forEach(clearTimeout);
    rapidTimers.current = RAPID_POLLS.map((ms) =>
      setTimeout(() => refresh(), ms),
    );
  }, [refresh]);

  const start = useCallback(async () => {
    setLoading(true);
    try {
      await apiStart();
      setStatus("running");
      rapidRefresh();
    } finally {
      setLoading(false);
    }
  }, [rapidRefresh]);

  const stop = useCallback(async () => {
    setLoading(true);
    try {
      await apiStop();
      setStatus("exited");
      setUrl(null);
    } finally {
      setLoading(false);
    }
  }, []);

  // Poll on interval
  useEffect(() => {
    refresh();
    const id = setInterval(refresh, POLL_INTERVAL);
    return () => {
      clearInterval(id);
      rapidTimers.current.forEach(clearTimeout);
    };
  }, [refresh]);

  return { status, url, loading, start, stop, refresh };
}
