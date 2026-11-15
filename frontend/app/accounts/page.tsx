"use client";

import Link from "next/link";
import { Suspense, useState } from "react";

import { ConnectedBanks } from "@/components/connected-banks";
import { MonthPicker } from "@/components/month-picker";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Card,
  CardAction,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { api, query, useApi, type AccountActivity, type BalanceSummary } from "@/lib/api";
import { useAutoSync } from "@/lib/use-auto-sync";
import {
  addMonths,
  currentMonth,
  daysSince,
  formatCurrency,
  formatDay,
  formatMonth,
  timeAgo,
  toIsoDate,
} from "@/lib/format";
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
  const [changes, setChanges] = useState(0); // bumped after Sync now, linking, or closing
  const changed = () => setChanges((c) => c + 1);
  const { data: accounts, error } = useApi<AccountActivity[]>(
    `/summary/accounts${query({ month })}`,
    syncKey + changes,
  );

  return (
    <>
      <h1 className="text-xl font-semibold">Accounts</h1>
      <Balances refreshKey={syncKey + changes} />

      <div className="flex flex-wrap items-center justify-between gap-3">
        <h2 className="text-lg font-semibold">Money in and out</h2>
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
          ? accounts.map((a) => (
              <AccountCard key={a.id} account={a} month={month} onChanged={changed} />
            ))
          : [0, 1].map((i) => <Skeleton key={i} className="h-48 rounded-xl" />)}
      </div>

      <ConnectedBanks syncKey={syncKey} onChanged={changed} />
    </>
  );
}

/** Cash, card debt and what's left, from the balances banks report through Plaid. */
function Balances({ refreshKey }: { refreshKey: number }) {
  const { data: b, error } = useApi<BalanceSummary>("/summary/balances", refreshKey);

  if (error) return <p className="text-sm text-destructive">{error}</p>;
  if (b && b.as_of === null) return null; // no bank on Plaid yet, so no balances to show

  return (
    <Card>
      <CardHeader>
        <CardTitle>Right now</CardTitle>
        <CardDescription>
          {b ? `Balances from your bank, ${timeAgo(b.as_of!)}.` : "Loading balances…"}
          {b && b.missing.length > 0 && ` Not included (no balance from Plaid): ${b.missing.join(", ")}.`}
        </CardDescription>
      </CardHeader>
      <CardContent>
        <dl className="grid grid-cols-1 gap-3 sm:grid-cols-3">
          <Amount label="Cash" hint="Chequing and savings" cents={b?.cash_cents} />
          <Amount label="Owed on cards" hint="Already spent" cents={b?.owed_cents} />
          <Amount
            label="Available"
            hint="Cash minus what you owe on cards"
            cents={b?.available_cents}
            tone={b && b.available_cents >= 0 ? "positive" : undefined}
          />
        </dl>
      </CardContent>
    </Card>
  );
}

function AccountCard({
  account: a,
  month,
  onChanged,
}: {
  account: AccountActivity;
  month: string;
  onChanged: () => void;
}) {
  const closed = a.closed_on !== null;
  // Plaid-linked accounts have their own sync status, under Connected banks; closed ones
  // expect nothing new.
  const stale =
    !closed && !a.plaid_linked && a.last_date !== null && daysSince(a.last_date) > STALE_DAYS;
  const net = a.money_in_cents - a.money_out_cents;
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function setClosed(closedOn: string | null) {
    setBusy(true);
    setError(null);
    try {
      await api(`/accounts/${a.id}`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ closed_on: closedOn }),
      });
      onChanged();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <Card className={cn(closed && "opacity-75")}>
      <CardHeader>
        <CardTitle className="flex items-center gap-2">
          {a.name}
          {closed && <Badge variant="secondary">Closed {formatDay(a.closed_on!)}</Badge>}
        </CardTitle>
        <CardDescription>
          {a.institution} · {TYPE_LABELS[a.type] ?? a.type}
          {a.plaid_linked && " · via Plaid"}
          {a.balance_cents !== null && !closed && (
            <>
              {" · "}
              {a.balance_cents < 0 ? "Owed " : "Balance "}
              <span className="tabular">{formatCurrency(Math.abs(a.balance_cents))}</span>
            </>
          )}
        </CardDescription>
        <CardAction>
          <Button
            variant="ghost"
            size="sm"
            disabled={busy}
            onClick={() => setClosed(closed ? null : toIsoDate(new Date()))}
            title={
              closed
                ? "Expect new transactions again"
                : "Stop expecting new transactions, and leave it out of available money. Its history stays."
            }
          >
            {closed ? "Reopen" : "Mark closed"}
          </Button>
        </CardAction>
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
        {error && <p className="text-sm text-destructive">{error}</p>}
      </CardContent>
    </Card>
  );
}

function Amount({
  label,
  cents,
  tone,
  signed = false,
  hint,
}: {
  label: string;
  cents: number | undefined; // undefined while loading
  tone?: "positive";
  signed?: boolean; // show "+" on a positive amount
  hint?: string;
}) {
  return (
    <div>
      <dt className="text-xs text-muted-foreground" title={hint}>
        {label}
      </dt>
      <dd className={cn("text-lg font-semibold tabular", tone === "positive" && "text-positive")}>
        {cents === undefined ? (
          <Skeleton className="h-7 w-24" />
        ) : (
          <>
            {signed && cents > 0 ? "+" : ""}
            {formatCurrency(cents)}
          </>
        )}
      </dd>
      {hint && <p className="text-xs text-muted-foreground">{hint}</p>}
    </div>
  );
}
