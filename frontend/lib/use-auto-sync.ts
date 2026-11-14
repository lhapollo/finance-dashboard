"use client";

import { useEffect, useState } from "react";

import { api, type SyncResult } from "@/lib/api";

// One automatic sync at a time, shared: in development React sets every page up twice on
// purpose, and two pages open at once shouldn't each start one either.
let running: Promise<SyncResult[]> | null = null;

function syncIfStale(): Promise<SyncResult[]> {
  running ??= api<SyncResult[]>("/plaid/sync", { method: "POST" }).finally(() => {
    running = null;
  });
  return running;
}

/**
 * Syncs connected banks when a page opens, if they haven't synced in the last few hours (the
 * backend decides). The page shows what it already has right away; `syncKey` goes up once
 * a sync has run, so pass it as a refresh key to reload the numbers.
 *
 * Failures stay quiet here: the Accounts page shows each bank's status.
 */
export function useAutoSync() {
  const [syncKey, setSyncKey] = useState(0);
  const [syncing, setSyncing] = useState(true);

  useEffect(() => {
    let cancelled = false;
    syncIfStale()
      .then((results) => {
        if (!cancelled && results.length > 0) setSyncKey((k) => k + 1);
      })
      .catch(() => {})
      .finally(() => {
        if (!cancelled) setSyncing(false);
      });
    return () => {
      cancelled = true;
    };
  }, []);

  return { syncKey, syncing };
}
