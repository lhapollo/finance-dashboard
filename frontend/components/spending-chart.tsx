"use client";

import { useRouter } from "next/navigation";
import { useMemo, useState } from "react";
import { Bar, BarChart, CartesianGrid, XAxis, YAxis, type XAxisTickContentProps } from "recharts";

import { Button } from "@/components/ui/button";
import { Card, CardAction, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { ChartContainer, ChartTooltip, type ChartConfig } from "@/components/ui/chart";
import { Skeleton } from "@/components/ui/skeleton";
import { query, useApi, type PeriodCategoryTotal } from "@/lib/api";
import { categoryColor, categoryLabel, OTHER, SERIES, toChartRows, type ChartRow } from "@/lib/categories";
import { addMonths, formatCompactCurrency, formatCurrency, formatMonth, monthStarts } from "@/lib/format";

const config: ChartConfig = Object.fromEntries(
  SERIES.map((s) => [
    s,
    { label: s === OTHER ? "Other" : categoryLabel(s), color: categoryColor(s) },
  ]),
);

type View = "month" | "year";

/** Stacked bars of spending per category: the last 12 months, or every year. */
export function SpendingChart({ month, refreshKey = 0 }: { month: string; refreshKey?: number }) {
  const [view, setView] = useState<View>("month");
  const router = useRouter();
  const { data, error } = useApi<PeriodCategoryTotal[]>(
    `/summary/over-time${query({ group_by: view, month })}`,
    refreshKey,
  );

  const rows = useMemo(() => {
    if (!data) return null;
    const periods =
      view === "month" ? monthStarts(month, 12) : [...new Set(data.map((d) => d.period))].sort();
    return toChartRows(data, periods);
  }, [data, view, month]);

  const label = (period: string, short: boolean) =>
    view === "year" ? period.slice(0, 4) : formatMonth(period, short);

  /** Lists a period's transactions. A segment opens its category in that month (or year);
   * "Other" mixes several categories, so it opens the whole period, as does the axis label. */
  function openTransactions(period: string, series: string) {
    const end =
      view === "year"
        ? `${Number(period.slice(0, 4)) + 1}-01-01`
        : `${addMonths(period.slice(0, 7), 1)}-01`;
    const category = series === OTHER ? undefined : series;
    router.push(`/transactions${query({ category, start: period, end })}`);
  }

  return (
    <Card>
      <CardHeader>
        <CardTitle>Spending over time</CardTitle>
        <CardDescription>
          {view === "month" ? "Last 12 months" : "Every year"}, by category · click a bar or{" "}
          {view === "month" ? "month" : "year"} to see its transactions
        </CardDescription>
        <CardAction>
          <div className="flex rounded-lg bg-muted p-0.5" role="group" aria-label="Group by">
            {(["month", "year"] as const).map((v) => (
              <Button
                key={v}
                size="xs"
                variant={view === v ? "outline" : "ghost"}
                aria-pressed={view === v}
                onClick={() => setView(v)}
              >
                {v === "month" ? "Monthly" : "Yearly"}
              </Button>
            ))}
          </div>
        </CardAction>
      </CardHeader>
      <CardContent>
        {error ? (
          <p className="text-sm text-destructive">{error}</p>
        ) : !rows ? (
          <Skeleton className="h-72 w-full" />
        ) : (
          <>
            <ChartContainer config={config} className="aspect-auto h-72 w-full">
              <BarChart data={rows} margin={{ left: 0, right: 0, top: 8 }}>
                <CartesianGrid vertical={false} />
                <XAxis
                  dataKey="period"
                  tickLine={false}
                  axisLine={false}
                  tickMargin={8}
                  interval={0} // every month gets a label (and a link), never skipped
                  tick={({ x, y, payload }: XAxisTickContentProps) => (
                    <PeriodTick
                      x={Number(x)}
                      y={Number(y)}
                      text={label(String(payload.value), true)}
                      fullText={label(String(payload.value), false)}
                      onOpen={() => openTransactions(String(payload.value), OTHER)}
                    />
                  )}
                />
                <YAxis
                  tickLine={false}
                  axisLine={false}
                  width={52}
                  className="tabular"
                  tickFormatter={(cents: number) => formatCompactCurrency(cents)}
                />
                <ChartTooltip
                  cursor={{ fillOpacity: 0.5 }}
                  content={({ active, payload, label: period }) =>
                    active && payload?.length ? (
                      <SpendingTooltip
                        title={label(String(period), false)}
                        row={payload[0].payload as ChartRow}
                      />
                    ) : null
                  }
                />
                {SERIES.map((s, i) => (
                  <Bar
                    key={s}
                    dataKey={s}
                    stackId="spending"
                    fill={`var(--color-${s})`}
                    maxBarSize={24}
                    // A 2px gap in the card color between stacked segments.
                    stroke="var(--card)"
                    strokeWidth={2}
                    radius={i === SERIES.length - 1 ? [4, 4, 0, 0] : 0}
                    isAnimationActive={false}
                    className="cursor-pointer"
                    onClick={(bar) => openTransactions((bar.payload as ChartRow).period, s)}
                  />
                ))}
              </BarChart>
            </ChartContainer>
            <Legend />
          </>
        )}
      </CardContent>
    </Card>
  );
}

/** An x-axis label ("Jan") that opens every transaction in that month. The invisible rect
 * gives it a hit area bigger than the text itself. */
function PeriodTick({
  x,
  y,
  text,
  fullText,
  onOpen,
}: {
  x: number;
  y: number;
  text: string;
  fullText: string;
  onOpen: () => void;
}) {
  return (
    <g
      role="link"
      tabIndex={0}
      aria-label={`All transactions in ${fullText}`}
      onClick={onOpen}
      onKeyDown={(e) => (e.key === "Enter" || e.key === " ") && (e.preventDefault(), onOpen())}
      className="group cursor-pointer outline-none"
    >
      <title>{`All transactions in ${fullText}`}</title>
      <rect x={x - 22} y={y - 2} width={44} height={24} fill="transparent" />
      <text
        x={x}
        y={y + 14}
        textAnchor="middle"
        className="fill-muted-foreground group-hover:fill-foreground group-hover:underline group-focus-visible:fill-foreground group-focus-visible:underline"
      >
        {text}
      </text>
    </g>
  );
}

function SpendingTooltip({ title, row }: { title: string; row: ChartRow }) {
  // Top of the stack first, so the list reads in the same order as the bar.
  const items = [...SERIES].reverse().filter((s) => (row[s] as number) > 0);
  const total = items.reduce((sum, s) => sum + (row[s] as number), 0);
  return (
    <div className="grid min-w-44 gap-1.5 rounded-lg border bg-popover px-3 py-2 text-xs shadow-md">
      <div className="flex justify-between gap-4 font-medium">
        <span>{title}</span>
        <span className="tabular">{formatCurrency(total)}</span>
      </div>
      {items.map((s) => (
        <div key={s} className="flex items-center gap-2 text-muted-foreground">
          <span className="size-2.5 shrink-0 rounded-[3px]" style={{ background: categoryColor(s) }} />
          <span className="flex-1">{s === OTHER ? "Other" : categoryLabel(s)}</span>
          <span className="tabular text-foreground">{formatCurrency(row[s] as number)}</span>
        </div>
      ))}
    </div>
  );
}

function Legend() {
  return (
    <ul className="mt-3 flex flex-wrap justify-center gap-x-4 gap-y-1 text-xs text-muted-foreground">
      {SERIES.map((s) => (
        <li key={s} className="flex items-center gap-1.5">
          <span className="size-2.5 rounded-[3px]" style={{ background: categoryColor(s) }} />
          {s === OTHER ? "Other" : categoryLabel(s)}
        </li>
      ))}
    </ul>
  );
}
