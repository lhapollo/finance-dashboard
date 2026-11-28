"use client";

import Link from "next/link";

import { FillBar } from "@/components/fill-bar";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { query, useApi, type CategoryTotal } from "@/lib/api";
import { SERIES, categoryColor, categoryLabel, seriesFor } from "@/lib/categories";
import { addMonths, formatCurrency, formatMonth } from "@/lib/format";
import { cn } from "@/lib/utils";

/** The month's spending per category, largest first, as labelled bars. Doubles as the
 * chart's table view: every category is listed by name with its exact amount. A category
 * where refunds outweighed spending shows its (negative) amount in green with no bar. */
export function CategoryBreakdown({
  month,
  refreshKey = 0,
}: {
  month: string;
  refreshKey?: number;
}) {
  const start = `${month}-01`;
  const end = `${addMonths(month, 1)}-01`;
  const { data, error } = useApi<CategoryTotal[]>(
    `/summary/categories${query({ start, end })}`,
    refreshKey,
  );
  const largest = Math.max(0, data?.[0]?.total_cents ?? 0);

  return (
    <Card>
      <CardHeader>
        <CardTitle>By category</CardTitle>
        <CardDescription>{formatMonth(start)}</CardDescription>
      </CardHeader>
      <CardContent>
        {error ? (
          <p className="text-sm text-destructive">{error}</p>
        ) : !data ? (
          <div className="flex flex-col gap-3">
            {[0, 1, 2, 3, 4].map((i) => (
              <Skeleton key={i} className="h-6 w-full" />
            ))}
          </div>
        ) : data.length === 0 ? (
          <p className="text-sm text-muted-foreground">No spending this month.</p>
        ) : (
          <div className="flex flex-col gap-4">
          <SplitBar totals={data} />
          <ul className="flex flex-col gap-2.5">
            {data.map(({ category, total_cents }) => (
              <li key={category}>
                <Link
                  href={`/transactions${query({ category, start, end })}`}
                  className="group grid gap-1 rounded-md transition-transform duration-200 ease-out hover:translate-x-1"
                >
                  <div className="flex items-baseline justify-between gap-2 text-sm">
                    <span className="flex items-center gap-2 group-hover:underline">
                      <span
                        className="size-2.5 shrink-0 rounded-[3px]"
                        style={{ background: categoryColor(category) }}
                      />
                      {categoryLabel(category)}
                    </span>
                    <span className={cn("tabular", total_cents < 0 && "text-positive")}>
                      {formatCurrency(total_cents)}
                    </span>
                  </div>
                  <div className="h-1.5 rounded-full bg-muted">
                    <FillBar
                      percent={total_cents > 0 ? Math.max(2, (total_cents / largest) * 100) : 0}
                      color={categoryColor(category)}
                    />
                  </div>
                </Link>
              </li>
            ))}
          </ul>
          </div>
        )}
      </CardContent>
    </Card>
  );
}

/** How the month's spending splits up, at a glance: one block per category, sized by its
 * share, in the same colors as the list below it (which gives the names and amounts).
 * Categories without a color slot are folded into one gray "Other" block at the end. The
 * list is the bar's legend and table view. */
function SplitBar({ totals }: { totals: CategoryTotal[] }) {
  const blocks = new Map<string, number>();
  for (const { category, total_cents } of totals) {
    if (total_cents <= 0) continue; // refunds outweighed spending: no share to show
    const series = seriesFor(category);
    blocks.set(series, (blocks.get(series) ?? 0) + total_cents);
  }
  // Fixed slot order, not biggest first: the palette is checked for colorblind-safe
  // neighbours in that order. The list below ranks them.
  const ordered = SERIES.filter((series) => blocks.has(series)).map(
    (series) => [series, blocks.get(series)!] as const,
  );
  const total = ordered.reduce((sum, [, cents]) => sum + cents, 0);
  if (total === 0) return null;

  return (
    <div
      className="flex h-3 w-full gap-0.5"
      role="img"
      aria-label={`Spending split: ${ordered
        .map(([series, cents]) => `${categoryLabel(series)} ${Math.round((cents / total) * 100)}%`)
        .join(", ")}`}
    >
      {ordered.map(([series, cents]) => {
        const pct = (cents / total) * 100;
        return (
          <div
            key={series}
            className="h-full min-w-1 rounded-[3px] transition-opacity hover:opacity-80"
            style={{ width: `${pct}%`, background: categoryColor(series) }}
            title={`${categoryLabel(series)}: ${formatCurrency(cents)} (${Math.round(pct)}%)`}
          />
        );
      })}
    </div>
  );
}
