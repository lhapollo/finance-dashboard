"use client";

import { useCallback, useEffect, useState } from "react";

/** Where the browser finds the FastAPI backend (set in .env). */
const API_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

// These mirror backend/app/schemas.py. Money is always integer cents.

export type Account = { id: number; name: string; institution: string; type: string };

export type Transaction = {
  id: number;
  account_id: number;
  date: string; // "2026-10-15"
  description: string; // the name to show
  cleaned_description: string; // the converter's name, before any rename
  description_source: "auto" | "rule" | "manual";
  raw_description: string;
  amount_cents: number; // negative = money out
  category: string;
  category_source: "rule" | "manual";
  is_transfer: boolean;
  transfer_source: "auto" | "manual";
  transfer_pair_id: number | null;
  // Paybacks: money in linked to a purchase counts in the purchase's category and month.
  reimburses_id: number | null; // on a payback: the purchase it pays back
  counted_category: string; // the purchase's category on a payback, otherwise `category`
  reimbursement_ids: number[]; // on a purchase: its paybacks, oldest first
  reimbursed_cents: number; // on a purchase: how much has been paid back (positive)
  imported_at: string;
};

export type TransactionPage = { items: Transaction[]; total: number };

export type MonthSummary = {
  month: string;
  spent_cents: number;
  income_cents: number;
  net_cents: number;
  previous_spent_cents: number;
  change_pct: number | null;
};

export type CategoryTotal = { category: string; total_cents: number };

export type PeriodCategoryTotal = { period: string; category: string; total_cents: number };

export type ImportResult = { inserted: number; skipped: number };

export class ApiError extends Error {}

/** Calls the backend and returns its JSON. Errors carry FastAPI's "detail" message. */
export async function api<T>(path: string, init?: RequestInit): Promise<T> {
  let response: Response;
  try {
    response = await fetch(`${API_URL}${path}`, init);
  } catch {
    throw new ApiError("Can't reach the backend. Is `docker compose up` running?");
  }
  if (!response.ok) {
    const body = await response.json().catch(() => null);
    const detail = body?.detail;
    // 422s from FastAPI list each invalid field; show the first one.
    const message = Array.isArray(detail) ? detail[0]?.msg : detail;
    throw new ApiError(message ?? `Request failed (${response.status})`);
  }
  return response.json() as Promise<T>;
}

/** Builds "?a=1&b=2", skipping empty values. */
export function query(params: Record<string, string | number | boolean | null | undefined>) {
  const search = new URLSearchParams();
  for (const [key, value] of Object.entries(params)) {
    if (value !== null && value !== undefined && value !== "") search.set(key, String(value));
  }
  const text = search.toString();
  return text ? `?${text}` : "";
}

/**
 * Loads `path` and reloads whenever it or `refreshKey` changes (bump the key after an edit
 * elsewhere on the page). `reload()` fetches again too. `data` keeps the previous result
 * while a new one loads, so the page doesn't flash empty.
 */
export function useApi<T>(path: string, refreshKey = 0) {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [version, setVersion] = useState(0);

  useEffect(() => {
    let cancelled = false; // ignore a slow response that arrives after the path changed
    api<T>(path)
      .then((result) => {
        if (!cancelled) {
          setData(result);
          setError(null);
        }
      })
      .catch((e: Error) => {
        if (!cancelled) setError(e.message);
      });
    return () => {
      cancelled = true;
    };
  }, [path, version, refreshKey]);

  const reload = useCallback(() => setVersion((v) => v + 1), []);
  return { data, error, reload };
}
