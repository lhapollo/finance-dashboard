"use client";

import Link from "next/link";
import { Suspense, useState } from "react";

import { ConnectedBanks } from "@/components/connected-banks";
import { MonthPicker } from "@/components/month-picker";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { query, useApi, type AccountActivity } from "@/lib/api";
import { useAutoSync } from "@/lib/use-auto-sync";
import { addMonths, currentMonth, daysSince, formatCurrency, formatDay, formatMonth } from "@/lib/format";
import { cn } from "@/lib/utils";

/** After this many days with nothing new, an account probably needs a newer CSV. */
const STALE_DAYS = 7;

const TYPE_LABELS: Record<string, string> = {
  credit: "Credit card",
  chequing: "Chequing",
  savings: "Savings",
  investment: "Investment",
};

export default function AccountsPage() {
  // The page depends on today's date, so it renders per visit (see the dashboard).
  return (
    <Suspense>
      <Accounts />
    </Suspense>
  );
}

function Accounts() {
  const [month, setMonth] = useState(currentMonth);
  const { syncKey } = useAutoSync();
  const [changes, setChanges] = useState(0); // bumped after Sync now or linking accounts
  const { data: accounts, error } = useApi<AccountActivity[]>(
    `/summary/accounts${query({ month })}`,
    syncKey + changes,
  );

  return (
    <>
      <div className="flex flex-wrap items-center justify-between gap-3">
        <h1 className="text-xl font-semibold">Accounts</h1>
        <MonthPicker month={month} onChange={setMonth} />
      </div>
      <p className="max-w-2xl text-sm text-muted-foreground">
        Money in and out as your bank shows it, transfers and card payments included, so each
        card should match that account’s statement for {formatMonth(`${month}-01`)}. The
        dashboard leaves transfers out, so its totals are different on purpose.
      </p>

      {error && <p className="text-sm text-destructive">{error}</p>}

      <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
        {accounts
          ? accounts.map((a) => <AccountCard key={a.id} account={a} month={month} />)
          : [0, 1].map((i) => <Skeleton key={i} className="h-48 rounded-xl" />)}
      </div>

      <ConnectedBanks syncKey={syncKey} onChanged={() => setChanges((c) => c + 1)} />
    </>
  );
}

function AccountCard({ account: a, month }: { account: AccountActivity; month: string }) {
  // Plaid-linked accounts have their own sync status, under Connected banks.
  const stale = !a.plaid_linked && a.last_date !== null && daysSince(a.last_date) > STALE_DAYS;
  const net = a.money_in_cents - a.money_out_cents;

  return (
    <Card>
      <CardHeader>
        <CardTitle>{a.name}</CardTitle>
        <CardDescription>
          {a.institution} · {TYPE_LABELS[a.type] ?? a.type}
          {a.plaid_linked && " · via Plaid"}
        </CardDescription>
      </CardHeader>
      <CardContent className="flex flex-col gap-4">
        <dl className="grid grid-cols-3 gap-3">
          <Amount label="Money in" cents={a.money_in_cents} tone="positive" />
          <Amount label="Money out" cents={a.money_out_cents} />
          <Amount label="Net" cents={net} tone={net >= 0 ? "positive" : undefined} signed />
        </dl>

        <div className="flex flex-col gap-1 text-sm">
          {a.first_date === null || a.last_date === null ? (
            <p className="text-muted-foreground">
              Nothing imported yet.{" "}
              <Link href={`/import${query({ account_id: a.id })}`} className="underline">
                Import a CSV
              </Link>
            </p>
          ) : (
            <>
              <p className="text-muted-foreground">
                {a.count} {a.count === 1 ? "transaction" : "transactions"} in{" "}
                {formatMonth(`${month}-01`)} ·{" "}
                <Link
                  href={`/transactions${query({
                    account_id: a.id,
                    start: `${month}-01`,
                    end: `${addMonths(month, 1)}-01`,
                  })}`}
                  className="underline"
                >
                  See them
                </Link>
              </p>
              <p className={cn(stale ? "text-foreground" : "text-muted-foreground")}>
                {a.plaid_linked ? "Transactions" : "Imported"} from {formatDay(a.first_date)} to{" "}
                {formatDay(a.last_date)}
                {stale && (
                  <>
                    . Nothing newer for {daysSince(a.last_date)} days:{" "}
                    <Link href={`/import${query({ account_id: a.id })}`} className="underline">
                      import a newer CSV
                    </Link>
                  </>
                )}
              </p>
            </>
          )}
        </div>
      </CardContent>
    </Card>
  );
}

function Amount({
  label,
  cents,
  tone,
  signed = false,
}: {
  label: string;
  cents: number;
  tone?: "positive";
  signed?: boolean; // show "+" on a positive amount
}) {
  return (
    <div>
      <dt className="text-xs text-muted-foreground">{label}</dt>
      <dd className={cn("text-lg font-semibold tabular", tone === "positive" && "text-positive")}>
        {signed && cents > 0 ? "+" : ""}
        {formatCurrency(cents)}
      </dd>
    </div>
  );
}
