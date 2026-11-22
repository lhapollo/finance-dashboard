"use client";

import { useCallback, useEffect, useState } from "react";

/** Where the browser finds the FastAPI backend (set in .env). */
const API_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

// These mirror backend/app/schemas.py. Money is always integer cents.

export type Account = {
  id: number;
  name: string;
  institution: string;
  type: string;
  closed_on: string | null; // set once I've closed it, e.g. cancelled a card
};

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
  // Someone will pay all of it back (a work expense), so it isn't counted as spending.
  reimbursable: boolean;
  reimbursement_status: "waiting" | "received" | null; // null unless reimbursable
  splits: Split[]; // empty unless split; when split, the parts count instead of the whole
  // Set only when I picked the bucket by hand ("manual"; bucket_id null = no bucket).
  // Otherwise the category's default bucket applies (see CategoryBucket).
  bucket_id: number | null;
  bucket_assigned_by: "manual" | null;
  source: "csv" | "plaid";
  pending: boolean; // Plaid only: not final yet, the amount can still change
  imported_at: string;
};

/** One part of a split transaction. Parts add up to the transaction's amount. */
export type Split = {
  id: number;
  amount_cents: number; // same sign as the transaction
  category: string;
  reimburses_id: number | null; // on money in: the purchase this part pays back
  counted_category: string; // the purchase's category if it pays one back
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

export type ReimbursementSummary = {
  waiting_cents: number; // still owed to me, all time (positive)
  count: number; // reimbursable purchases not fully paid back yet
};

export type CategoryTotal = { category: string; total_cents: number };

export type PeriodCategoryTotal = { period: string; category: string; total_cents: number };

/** One account's month as the bank shows it (transfers included), for checking statements. */
export type AccountActivity = Account & {
  money_in_cents: number; // this month, positive
  money_out_cents: number; // this month, positive
  count: number; // transactions this month
  first_date: string | null; // oldest transaction imported, any month
  last_date: string | null; // newest transaction imported, any month
  plaid_linked: boolean; // new transactions come from Plaid, not CSVs
  balance_cents: number | null; // from the bank via Plaid; negative = owed
  balance_updated_at: string | null;
};

/** Money right now, from bank balances. available = cash - owed. Closed accounts left out. */
export type BalanceSummary = {
  cash_cents: number;
  owed_cents: number; // on credit cards, positive
  available_cents: number;
  as_of: string | null; // the oldest balance in the total
  missing: string[]; // open accounts with no balance (not on Plaid)
};

export type ImportResult = {
  inserted: number;
  skipped: number; // already imported, or after_cutoff
  after_cutoff: number; // rows on days Plaid covers for this account
};

/** Whether Plaid keys are in .env; `problem` says what's missing when they aren't. */
export type PlaidStatus = {
  configured: boolean;
  environment: "sandbox" | "production";
  problem: string | null;
};

/** A bank login connected through Plaid. The access token stays on the backend. */
export type PlaidItem = {
  id: number;
  institution_name: string;
  environment: "sandbox" | "production";
  status: string; // "ok", or Plaid's error code from the last sync
  last_synced_at: string | null;
  // When Plaid last got new data from the bank itself (null before its first check).
  bank_updated_at: string | null;
  created_at: string;
};

/** One account inside a connected bank, and which of my accounts it's linked to. */
export type PlaidAccount = {
  plaid_account_id: string;
  name: string;
  mask: string | null; // last 4 digits
  type: string;
  subtype: string | null;
  account_id: number | null; // linked to this account of mine
  suggested_account_id: number | null; // looks like this one, when not linked yet
};

/** What one bank's sync did. */
export type SyncResult = {
  item_id: number;
  institution_name: string;
  added: number;
  matched: number; // already imported from a CSV, so not added again
  updated: number;
  removed: number;
  unlinked_accounts: string[];
  error: string | null;
};

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

/** Sends a change and returns the error message, or null when it worked. */
export async function send(path: string, method: string, body?: object): Promise<string | null> {
  try {
    await api(path, {
      method,
      headers: { "Content-Type": "application/json" },
      body: body === undefined ? undefined : JSON.stringify(body),
    });
    return null;
  } catch (e) {
    return (e as Error).message;
  }
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

/** A bucket: a job for some of my money. Mirrors BucketOut in backend/app/schemas.py. */
export type Bucket = {
  id: number;
  name: string;
  type: "recurring" | "goal";
  target_amount_cents: number | null; // required for goals
  target_date: string | null; // optional, goals only
  archived: boolean;
  allocated_cents: number; // put in, minus taken out
  spent_cents: number; // spending out of it since the budget started
  balance_cents: number; // allocated - spent: what's left
  progress_pct: number | null; // goals: balance as a % of the target
};

/** The whole budget. unassigned = available - in buckets. */
export type Budget = {
  start_date: string | null; // null until the fresh-start setup is done
  available_cents: number | null; // null: no bank balances (connect a bank)
  available_as_of: string | null;
  assigned_cents: number;
  unassigned_cents: number | null; // negative: more in buckets than you have
  unbucketed_spent_cents: number; // spending since the start that no bucket covers
  buckets: Bucket[]; // open first, archived last
};

/** A spending category and the bucket its spending comes out of by default. */
export type CategoryBucket = {
  category: string;
  bucket_id: number | null;
  spent_cents: number; // since the budget started
};

/** How to recognize a paycheck: money in to `account_id` whose description contains
 * `match_text`. */
export type IncomeSource = {
  id: number;
  name: string;
  account_id: number;
  match_text: string;
  active: boolean;
};

/** A deposit that keeps coming in as income, so probably a paycheck. */
export type IncomeSourceSuggestion = {
  account_id: number;
  match_text: string;
  count: number;
  last_date: string;
  last_amount_cents: number;
};

/** One line of the usual paycheck split. Fixed amounts apply first, then percents of what's
 * left after them. */
export type PaycheckRule = {
  bucket_id: number;
  kind: "fixed" | "percent";
  amount_cents: number | null;
  percent: number | null;
};

export type BucketAmount = { bucket_id: number; amount_cents: number };

export type Paycheck = {
  transaction_id: number;
  date: string;
  description: string;
  account_id: number;
  deposit_cents: number;
  paycheck_cents: number; // the pay part (a split deposit's income parts)
  detected: boolean;
  override: boolean | null; // marked by hand
  is_paycheck: boolean;
  splittable: boolean; // on or after the budget start
  split: BucketAmount[];
  split_cents: number;
};

export type PaycheckSplitSuggestion = {
  paycheck_cents: number;
  suggested: BucketAmount[];
  leftover_cents: number;
};

/** One tool the AI used to answer, with what it asked for and what it got back. */
export type AskStep = {
  tool: string;
  arguments: Record<string, unknown>;
  result: Record<string, unknown>;
};

export type AskResponse = { answer: string; steps: AskStep[] };
