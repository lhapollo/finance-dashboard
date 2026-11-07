"use client";

import Link from "next/link";
import { Suspense, useState } from "react";

import { CategoryBreakdown } from "@/components/category-breakdown";
import { MonthPicker } from "@/components/month-picker";
import { SpendingChart } from "@/components/spending-chart";
import { StatCard } from "@/components/stat-card";
import { TransactionsTable } from "@/components/transactions-table";
import { Card, CardAction, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { query, useApi, type MonthSummary } from "@/lib/api";
import { addMonths, currentMonth, formatCurrency, formatMonth, formatWholeDollars } from "@/lib/format";

export default function DashboardPage() {
  // The dashboard depends on today's date, so Next.js must render it per visit, not once
  // at build time. Suspense marks that boundary.
  return (
    <Suspense>
      <Dashboard />
    </Suspense>
  );
}

function Dashboard() {
  const [month, setMonth] = useState(currentMonth);
  // Bumped after an edit in the table, so every total on the page reloads.
  const [refreshKey, setRefreshKey] = useState(0);
  const refresh = () => setRefreshKey((k) => k + 1);

  const { data: summary, error } = useApi<MonthSummary>(
    `/summary/month${query({ month })}`,
    refreshKey,
  );
  const previous = formatMonth(`${addMonths(month, -1)}-01`, true);

  return (
    <>
      <div className="flex flex-wrap items-center justify-between gap-3">
        <h1 className="text-xl font-semibold">Dashboard</h1>
        <MonthPicker month={month} onChange={setMonth} />
      </div>

      {error && <p className="text-sm text-destructive">{error}</p>}

      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-4">
        <StatCard
          label="Spent"
          value={summary ? formatWholeDollars(summary.spent_cents) : null}
          detail={summary && `${formatCurrency(summary.spent_cents)} in ${formatMonth(summary.month)}`}
        />
        <StatCard
          label={`Change vs ${previous}`}
          value={
            summary
              ? summary.change_pct === null
                ? "—"
                : `${summary.change_pct > 0 ? "+" : ""}${summary.change_pct}%`
              : null
          }
          // Spending going down is the good direction.
          detailTone={
            !summary || summary.change_pct === null
              ? "muted"
              : summary.change_pct > 0
                ? "negative"
                : "positive"
          }
          detail={
            summary &&
            `${summary.spent_cents > summary.previous_spent_cents ? "Up" : "Down"} from ${formatWholeDollars(summary.previous_spent_cents)} in ${previous}`
          }
        />
        <StatCard
          label="Income"
          value={summary ? formatWholeDollars(summary.income_cents) : null}
          detail="Income and cashback. Refunds lower spending instead"
        />
        <StatCard
          label="Net"
          value={summary ? formatWholeDollars(summary.net_cents) : null}
          detailTone={summary && summary.net_cents >= 0 ? "positive" : "muted"}
          detail="Income minus spending"
        />
      </div>

      <div className="grid grid-cols-1 gap-4 lg:grid-cols-3">
        <div className="lg:col-span-2">
          <SpendingChart month={month} refreshKey={refreshKey} />
        </div>
        <CategoryBreakdown month={month} refreshKey={refreshKey} />
      </div>

      <Card>
        <CardHeader>
          <CardTitle>Recent transactions</CardTitle>
          <CardAction>
            <Link href="/transactions" className="text-sm text-muted-foreground hover:underline">
              View all
            </Link>
          </CardAction>
        </CardHeader>
        <CardContent>
          <TransactionsTable
            filters={{ start: `${month}-01`, end: `${addMonths(month, 1)}-01` }}
            pageSize={10}
            paged={false}
            onEdited={refresh}
          />
        </CardContent>
      </Card>
    </>
  );
}
