// API health state for the header indicator (design: GET /health on mount).
// UI-5: a 200 /health with status "ok" → "ok" (indicator shows connected);
// any failure (network error, non-2xx, unexpected body) → "degraded";
// "unknown" is the initial state before the first check resolves.

import { useCallback, useEffect, useState } from "react";
import { health } from "../api/client";

export type HealthStatus = "ok" | "degraded" | "unknown";

export function useHealth() {
  const [status, setStatus] = useState<HealthStatus>("unknown");

  const check = useCallback(async () => {
    try {
      const response = await health();
      setStatus(response.status === "ok" ? "ok" : "degraded");
    } catch {
      setStatus("degraded");
    }
  }, []);

  useEffect(() => {
    void check();
  }, [check]);

  return { status };
}