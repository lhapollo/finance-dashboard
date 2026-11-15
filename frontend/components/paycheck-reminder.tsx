"use client";

import Link from "next/link";

import { useApi, type Paycheck } from "@/lib/api";
import { formatCurrency } from "@/lib/format";

/** "New paycheck: $3,252.08 isn't split into buckets yet. Split it". Nothing when there's
 * nothing to split. */
export function PaycheckReminder({ refreshKey = 0 }: { refreshKey?: number }) {
  const { data } = useApi<Paycheck[]>("/paychecks", refreshKey);
  const waiting = (data ?? []).filter((p) => p.is_paycheck && p.splittable && p.split_cents === 0);
  if (waiting.length === 0) return null;

  const total = waiting.reduce((sum, p) => sum + p.paycheck_cents, 0);
  return (
    <p className="rounded-lg border border-positive/40 bg-positive/5 px-3 py-2 text-sm">
      {waiting.length === 1 ? "New paycheck: " : `${waiting.length} new paychecks: `}
      <span className="font-medium tabular">{formatCurrency(total)}</span> isn&apos;t split into
      buckets yet.{" "}
      <Link href="/buckets/paychecks" className="font-medium underline">
        Split {waiting.length === 1 ? "it" : "them"}
      </Link>
    </p>
  );
}
