"use client";

import Link from "next/link";

import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { query, useApi, type CategoryTotal } from "@/lib/api";
import { categoryColor, categoryLabel } from "@/lib/categories";
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
          <ul className="flex flex-col gap-2.5">
            {data.map(({ category, total_cents }) => (
              <li key={category}>
                <Link
                  href={`/transactions${query({ category, start, end })}`}
                  className="group grid gap-1 rounded-md"
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
                    <div
                      className="h-full rounded-full"
                      style={{
                        width: total_cents > 0 ? `${Math.max(2, (total_cents / largest) * 100)}%` : 0,
                        background: categoryColor(category),
                      }}
                    />
                  </div>
                </Link>
              </li>
            ))}
          </ul>
        )}
      </CardContent>
    </Card>
  );
}
