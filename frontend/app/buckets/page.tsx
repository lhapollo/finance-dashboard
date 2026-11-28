"use client";

import Link from "next/link";
import { Suspense, useState } from "react";
import { toast } from "sonner";

import { AnimatedNumber } from "@/components/animated-number";
import { FillBar } from "@/components/fill-bar";
import { MoneyInput } from "@/components/money-input";
import { PaycheckReminder } from "@/components/paycheck-reminder";
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
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Skeleton } from "@/components/ui/skeleton";
import { query, send, useApi, type Bucket, type Budget, type CategoryBucket } from "@/lib/api";
import { checkOpening, goalStatus } from "@/lib/budget";
import {
  ALL_CATEGORIES,
  INCOME_CATEGORIES,
  categoryColor,
  categoryLabel,
} from "@/lib/categories";
import { formatCurrency, formatDay, timeAgo, toIsoDate } from "@/lib/format";
import { parseDollars } from "@/lib/splits";
import { useAutoSync } from "@/lib/use-auto-sync";
import { cn } from "@/lib/utils";

export default function BucketsPage() {
  // Depends on today's date and live balances, so it renders per visit (see the dashboard).
  return (
    <Suspense>
      <Buckets />
    </Suspense>
  );
}

function Buckets() {
  const { syncKey } = useAutoSync();
  const { data: budget, error, reload } = useApi<Budget>("/budget", syncKey);
  const [startingOver, setStartingOver] = useState(false);

  return (
    <>
      <h1 className="text-xl font-semibold">Buckets</h1>
      {error && <p className="text-sm text-destructive">{error}</p>}
      {!budget ? (
        <Skeleton className="h-64 rounded-xl" />
      ) : budget.start_date === null || startingOver ? (
        <Setup
          budget={budget}
          reload={reload}
          onDone={() => setStartingOver(false)}
          onCancel={budget.start_date === null ? undefined : () => setStartingOver(false)}
        />
      ) : (
        <Overview budget={budget} reload={reload} onStartOver={() => setStartingOver(true)} />
      )}
    </>
  );
}

// --- Setup: the fresh start ---------------------------------------------------------------

function Setup({
  budget,
  reload,
  onDone,
  onCancel,
}: {
  budget: Budget;
  reload: () => void;
  onDone: () => void;
  onCancel?: () => void; // when starting over, to keep the current budget instead
}) {
  const open = budget.buckets.filter((b) => !b.archived);
  const [typed, setTyped] = useState<Record<number, string>>({});
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Money I'm owed is mine too, so the fresh start splits it along with available money.
  const available = budget.available_cents === null ? null : budget.available_cents + budget.owed_to_me_cents;
  const check = available === null ? null : checkOpening(available, open.map((b) => typed[b.id] ?? ""));

  async function start() {
    setSaving(true);
    const problem = await send("/budget/start", "POST", {
      start_date: toIsoDate(new Date()),
      opening: open.map((b) => ({
        bucket_id: b.id,
        amount_cents: parseDollars(typed[b.id] ?? "") ?? 0,
      })),
    });
    setSaving(false);
    setError(problem);
    if (!problem) {
      reload();
      onDone();
      toast.success("Budget started");
    }
  }

  async function remove(b: Bucket) {
    const problem = await send(`/buckets/${b.id}`, "DELETE");
    setError(problem);
    if (!problem) toast.success(`Deleted ${b.name}`);
    reload();
  }

  return (
    <>
      <p className="max-w-2xl text-sm text-muted-foreground">
        Give every dollar a job. Buckets are labels for parts of your money (rent, groceries, a
        Switch 2); the money itself stays in your accounts. Start by making your buckets, then
        split the money you have today across them. Anything you leave out stays{" "}
        <strong>unassigned</strong>, free to give a job later.
      </p>
      {onCancel && (
        <p className="text-sm">
          Starting over replaces everything you&apos;ve put in buckets so far.{" "}
          <button type="button" className="underline" onClick={onCancel}>
            Keep my current budget
          </button>
        </p>
      )}

      <Card>
        <CardHeader>
          <CardTitle>1. Your buckets</CardTitle>
          <CardDescription>
            Recurring buckets get spent every paycheck (rent, groceries). Goals are things you
            save up for, with a target.
          </CardDescription>
        </CardHeader>
        <CardContent className="flex flex-col gap-4">
          {open.length > 0 && (
            <ul className="flex flex-col divide-y text-sm">
              {open.map((b) => (
                <li key={b.id} className="flex items-center justify-between gap-3 py-2">
                  <span>
                    {b.name}{" "}
                    <span className="text-muted-foreground">
                      · {b.type === "goal" ? `Goal, ${formatCurrency(b.target_amount_cents!)}` : "Recurring"}
                    </span>
                  </span>
                  {b.allocated_cents === 0 && (
                    <Button variant="ghost" size="sm" onClick={() => remove(b)}>
                      Remove
                    </Button>
                  )}
                </li>
              ))}
            </ul>
          )}
          <NewBucketForm onCreated={reload} />
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>2. Split your money</CardTitle>
          <CardDescription>
            {available === null ? (
              <>
                The budget needs your bank balances to know how much you have.{" "}
                <Link href="/accounts" className="underline">
                  Connect a bank
                </Link>{" "}
                first.
              </>
            ) : (
              <>
                You have <strong className="tabular">{formatCurrency(available)}</strong>{" "}
                available: cash minus what you owe on cards, as of{" "}
                {timeAgo(budget.available_as_of!)}
                {budget.owed_to_me_cents > 0 && (
                  <>, including {formatCurrency(budget.owed_to_me_cents)} you&apos;re waiting to be paid back</>
                )}
                .
              </>
            )}
          </CardDescription>
        </CardHeader>
        {available !== null && check && (
          <CardContent className="flex flex-col gap-3 text-sm">
            {open.length === 0 ? (
              <p className="text-muted-foreground">Make a bucket first.</p>
            ) : (
              <>
                <ul className="flex flex-col gap-2">
                  {open.map((b) => (
                    <li key={b.id} className="flex items-center gap-3">
                      <Label htmlFor={`opening-${b.id}`} className="min-w-40 flex-1 font-normal">
                        {b.name}
                      </Label>
                      <MoneyInput
                        id={`opening-${b.id}`}
                        value={typed[b.id] ?? ""}
                        onChange={(v) => setTyped((t) => ({ ...t, [b.id]: v }))}
                      />
                    </li>
                  ))}
                </ul>
                <p className={cn("tabular", check.leftCents < 0 && "text-destructive")}>
                  Left unassigned: <strong>{formatCurrency(check.leftCents)}</strong>
                </p>
                {(check.problem ?? error) && (
                  <p className="text-destructive">{check.problem ?? error}</p>
                )}
                <div>
                  <Button onClick={start} disabled={saving || check.problem !== null}>
                    {saving ? "Saving…" : `Start budgeting from today`}
                  </Button>
                </div>
              </>
            )}
          </CardContent>
        )}
      </Card>
    </>
  );
}

// --- Overview: the running budget ---------------------------------------------------------

function Overview({
  budget,
  reload,
  onStartOver,
}: {
  budget: Budget;
  reload: () => void;
  onStartOver: () => void;
}) {
  const open = budget.buckets.filter((b) => !b.archived);
  const archived = budget.buckets.filter((b) => b.archived);
  const unassigned = budget.unassigned_cents;

  return (
    <>
      {/* Splitting a paycheck changes unassigned money, so that's what reloads it. */}
      <PaycheckReminder refreshKey={budget.unassigned_cents ?? 0} />
      <Card>
        <CardContent className="flex flex-col gap-3">
          <dl className="grid grid-cols-1 gap-3 sm:grid-cols-3">
            <Stat
              label="Unassigned"
              cents={unassigned}
              tone={unassigned === null ? undefined : unassigned < 0 ? "negative" : "positive"}
            />
            <Stat label="In buckets" cents={budget.assigned_cents} />
            <Stat label="Available" cents={budget.available_cents} />
          </dl>
          <p className="text-sm text-muted-foreground">
            {unassigned === null
              ? "Connect a bank on the Accounts page to see what's unassigned."
              : unassigned < 0
                ? "More is in buckets than you actually have. Take some back from a bucket."
                : unassigned > 0
                  ? "Unassigned money has no job yet. Add it to a bucket."
                  : "Every dollar has a job."}{" "}
            Budgeting since {formatDay(budget.start_date!)}
            {budget.available_as_of && `; balances from ${timeAgo(budget.available_as_of)}`}.
          </p>
          {budget.owed_to_me_cents > 0 && (
            <p className="text-sm">
              <strong className="tabular">{formatCurrency(budget.owed_to_me_cents)}</strong> you&apos;re
              waiting to be paid back ({budget.owed_to_me_count}{" "}
              {budget.owed_to_me_count === 1 ? "purchase" : "purchases"}) is already gone from
              Available, but it&apos;s still yours, so it counts in Unassigned.{" "}
              <Link href={`/transactions${query({ reimbursable: true })}`} className="underline">
                See what you&apos;re owed
              </Link>
            </p>
          )}
          {budget.unbucketed_spent_cents !== 0 && (
            <p className="text-sm">
              <strong className="tabular">{formatCurrency(budget.unbucketed_spent_cents)}</strong>{" "}
              of spending since then isn&apos;t from any bucket, so it came out of unassigned.{" "}
              <Link href={`/transactions${query({ unbucketed: true })}`} className="underline">
                See it
              </Link>{" "}
              or give its categories a bucket below.
            </p>
          )}
        </CardContent>
      </Card>

      {GROUPS.map(({ type, title, blurb }) => {
        const group = open.filter((b) => b.type === type);
        if (group.length === 0) return null;
        const total = group.reduce((sum, b) => sum + b.balance_cents, 0);
        return (
          <section key={type} className="flex flex-col gap-3">
            <div className="flex items-baseline justify-between gap-2">
              <div>
                <h2 className="font-medium">{title}</h2>
                <p className="text-sm text-muted-foreground">{blurb}</p>
              </div>
              <span className="text-sm text-muted-foreground tabular">{formatCurrency(total)}</span>
            </div>
            <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
              {group.map((b) => (
                <BucketCard key={b.id} bucket={b} others={open.filter((o) => o.id !== b.id)} reload={reload} />
              ))}
            </div>
          </section>
        );
      })}

      <Card className="md:max-w-[calc(50%-0.5rem)]">
        <CardHeader>
          <CardTitle>Add a bucket</CardTitle>
        </CardHeader>
        <CardContent>
          <NewBucketForm onCreated={reload} />
        </CardContent>
      </Card>

      <CategoryDefaults buckets={open} startDate={budget.start_date!} onChanged={reload} />

      {archived.length > 0 && (
        <section className="flex flex-col gap-2 text-sm">
          <h2 className="font-medium">Archived</h2>
          <ul className="flex flex-wrap gap-2">
            {archived.map((b) => (
              <ArchivedBucket key={b.id} bucket={b} reload={reload} />
            ))}
          </ul>
        </section>
      )}

      <p className="text-sm text-muted-foreground">
        <Link href="/buckets/paychecks" className="underline">
          Paychecks and your usual split
        </Link>{" "}
        · Want a clean slate?{" "}
        <button type="button" className="underline" onClick={onStartOver}>
          Start over
        </button>
      </p>
    </>
  );
}

/** Buckets are shown in two groups: spent and refilled, or saved up. */
const GROUPS = [
  { type: "recurring", title: "Recurring", blurb: "Refilled and spent every paycheck" },
  { type: "goal", title: "Goals", blurb: "Saved up for something" },
] as const;

function Stat({
  label,
  cents,
  tone,
}: {
  label: string;
  cents: number | null;
  tone?: "positive" | "negative";
}) {
  return (
    <div>
      <dt className="text-xs text-muted-foreground">{label}</dt>
      <dd
        className={cn(
          "text-2xl font-semibold tabular",
          tone === "positive" && "text-positive",
          tone === "negative" && "text-destructive",
        )}
      >
        {cents === null ? "—" : <AnimatedNumber value={cents} format={formatCurrency} />}
      </dd>
    </div>
  );
}

type Panel = "money" | "move" | "edit" | null;

function BucketCard({
  bucket: b,
  others,
  reload,
}: {
  bucket: Bucket;
  others: Bucket[];
  reload: () => void;
}) {
  const [panel, setPanel] = useState<Panel>(null);
  const [error, setError] = useState<string | null>(null);
  const toggle = (p: Panel) => {
    setError(null);
    setPanel((current) => (current === p ? null : p));
  };

  /** Runs a change; closes the panel when it works, shows the error when it doesn't. */
  async function change(path: string, method: string, body: object, done: string) {
    const problem = await send(path, method, body);
    setError(problem);
    if (!problem) {
      setPanel(null);
      reload();
      toast.success(done);
    }
  }

  async function archive() {
    const leftover =
      b.balance_cents !== 0 ? ` Its ${formatCurrency(b.balance_cents)} goes back to unassigned.` : "";
    if (window.confirm(`Archive ${b.name}?${leftover}`)) {
      await change(`/buckets/${b.id}`, "PATCH", { archived: true }, `Archived ${b.name}`);
    }
  }

  return (
    <Card>
      <CardHeader>
        <CardTitle>{b.name}</CardTitle>
        <CardDescription>{b.type === "goal" ? "Goal" : "Recurring"}</CardDescription>
        <CardAction>
          <p
            className={cn(
              "text-2xl font-semibold tabular",
              b.balance_cents < 0 && "text-destructive",
            )}
          >
            <AnimatedNumber value={b.balance_cents} format={formatCurrency} />
          </p>
        </CardAction>
      </CardHeader>
      <CardContent className="flex flex-col gap-3 text-sm">
        <p className="text-muted-foreground">
          {formatCurrency(b.allocated_cents)} put in · {formatCurrency(b.spent_cents)} spent ·{" "}
          <Link href={`/transactions${query({ bucket_id: b.id })}`} className="underline">
            See spending
          </Link>
        </p>
        {b.balance_cents < 0 && (
          <Badge variant="destructive" className="w-fit">
            Overspent: move money in to cover it
          </Badge>
        )}
        {b.type === "goal" && b.target_amount_cents !== null && (
          <div className="flex flex-col gap-1">
            <div
              className="h-2 overflow-hidden rounded-full bg-muted"
              role="progressbar"
              aria-label={`${b.name} progress`}
              aria-valuenow={b.progress_pct ?? 0}
              aria-valuemin={0}
              aria-valuemax={100}
            >
              <FillBar percent={b.progress_pct ?? 0} className="bg-positive" />
            </div>
            <p className="text-muted-foreground">
              {formatCurrency(Math.max(b.balance_cents, 0))} of{" "}
              {formatCurrency(b.target_amount_cents)} ·{" "}
              {goalStatus(b.balance_cents, b.target_amount_cents, b.target_date)}
            </p>
          </div>
        )}

        <div className="flex flex-wrap gap-1">
          <Button variant={panel === "money" ? "secondary" : "outline"} size="sm" onClick={() => toggle("money")}>
            Add or take out
          </Button>
          {others.length > 0 && (
            <Button variant={panel === "move" ? "secondary" : "outline"} size="sm" onClick={() => toggle("move")}>
              Move
            </Button>
          )}
          <Button variant={panel === "edit" ? "secondary" : "ghost"} size="sm" onClick={() => toggle("edit")}>
            Edit
          </Button>
          <Button variant="ghost" size="sm" onClick={archive}>
            Archive
          </Button>
        </div>

        {panel === "money" && (
          <MoneyPanel
            onSubmit={(cents, direction) =>
              change(
                "/budget/assign",
                "POST",
                { bucket_id: b.id, amount_cents: direction === "in" ? cents : -cents },
                direction === "in"
                  ? `Added ${formatCurrency(cents)} to ${b.name}`
                  : `Took ${formatCurrency(cents)} back from ${b.name}`,
              )
            }
          />
        )}
        {panel === "move" && (
          <MovePanel
            from={b}
            others={others}
            onSubmit={(toId, cents) =>
              change(
                "/budget/move",
                "POST",
                { from_bucket_id: b.id, to_bucket_id: toId, amount_cents: cents },
                `Moved ${formatCurrency(cents)} to ${others.find((o) => o.id === toId)?.name ?? "the other bucket"}`,
              )
            }
          />
        )}
        {panel === "edit" && (
          <EditPanel
            bucket={b}
            onSubmit={(fields) => change(`/buckets/${b.id}`, "PATCH", fields, "Bucket saved")}
          />
        )}
        {error && <p className="text-destructive">{error}</p>}
      </CardContent>
    </Card>
  );
}

function MoneyPanel({ onSubmit }: { onSubmit: (cents: number, direction: "in" | "out") => void }) {
  const [text, setText] = useState("");
  const cents = parseDollars(text);
  return (
    <div className="flex flex-wrap items-center gap-2">
      <MoneyInput value={text} onChange={setText} aria-label="Amount" autoFocus />
      <Button size="sm" disabled={cents === null} onClick={() => onSubmit(cents!, "in")}>
        Add from unassigned
      </Button>
      <Button size="sm" variant="outline" disabled={cents === null} onClick={() => onSubmit(cents!, "out")}>
        Take back
      </Button>
    </div>
  );
}

function MovePanel({
  from,
  others,
  onSubmit,
}: {
  from: Bucket;
  others: Bucket[];
  onSubmit: (toId: number, cents: number) => void;
}) {
  const [text, setText] = useState("");
  const [to, setTo] = useState(String(others[0].id));
  const cents = parseDollars(text);
  return (
    <div className="flex flex-wrap items-center gap-2">
      <MoneyInput value={text} onChange={setText} aria-label="Amount to move" autoFocus />
      <span>to</span>
      <Select
        items={Object.fromEntries(others.map((o) => [String(o.id), o.name]))}
        value={to}
        onValueChange={(v) => setTo(v as string)}
      >
        <SelectTrigger className="w-44" aria-label={`Move from ${from.name} to`}>
          <SelectValue />
        </SelectTrigger>
        <SelectContent>
          {others.map((o) => (
            <SelectItem key={o.id} value={String(o.id)}>
              {o.name}
            </SelectItem>
          ))}
        </SelectContent>
      </Select>
      <Button size="sm" disabled={cents === null} onClick={() => onSubmit(Number(to), cents!)}>
        Move
      </Button>
    </div>
  );
}

function EditPanel({
  bucket: b,
  onSubmit,
}: {
  bucket: Bucket;
  onSubmit: (fields: object) => void;
}) {
  const [name, setName] = useState(b.name);
  const [target, setTarget] = useState(b.target_amount_cents ? String(b.target_amount_cents / 100) : "");
  const [date, setDate] = useState(b.target_date ?? "");
  const targetCents = parseDollars(target);
  const goal = b.type === "goal";
  const ok = name.trim() !== "" && (!goal || targetCents !== null);

  return (
    <form
      className="flex flex-col gap-2"
      onSubmit={(e) => {
        e.preventDefault();
        onSubmit(
          goal
            ? { name, target_amount_cents: targetCents, target_date: date || null }
            : { name },
        );
      }}
    >
      <Label className="flex flex-col items-start gap-1 font-normal">
        Name
        <Input value={name} onChange={(e) => setName(e.target.value)} className="w-56" />
      </Label>
      {goal && (
        <div className="flex flex-wrap gap-3">
          <Label className="flex flex-col items-start gap-1 font-normal">
            Target
            <MoneyInput value={target} onChange={setTarget} />
          </Label>
          <Label className="flex flex-col items-start gap-1 font-normal">
            By (optional)
            <Input type="date" value={date} onChange={(e) => setDate(e.target.value)} className="w-40" />
          </Label>
        </div>
      )}
      <div>
        <Button type="submit" size="sm" disabled={!ok}>
          Save
        </Button>
      </div>
    </form>
  );
}

function ArchivedBucket({ bucket: b, reload }: { bucket: Bucket; reload: () => void }) {
  const [error, setError] = useState<string | null>(null);
  return (
    <li className="flex items-center gap-1 rounded-md border px-2 py-1">
      {b.name}
      <Button
        variant="ghost"
        size="sm"
        onClick={async () => {
          const problem = await send(`/buckets/${b.id}`, "PATCH", { archived: false });
          setError(problem);
          if (!problem) {
            reload();
            toast.success(`${b.name} is back`);
          }
        }}
      >
        Unarchive
      </Button>
      {error && <span className="text-destructive">{error}</span>}
    </li>
  );
}

/** Which bucket each category's spending comes out of by default. */
function CategoryDefaults({
  buckets,
  startDate,
  onChanged,
}: {
  buckets: Bucket[];
  startDate: string;
  onChanged: () => void;
}) {
  const { data, error, reload } = useApi<CategoryBucket[]>("/budget/categories");
  const [saveError, setSaveError] = useState<string | null>(null);

  /** A new recurring bucket named after the category, and made its default. */
  async function makeBucket(category: string) {
    const problem = await send("/buckets", "POST", {
      name: categoryLabel(category),
      type: "recurring",
      category,
    });
    setSaveError(problem);
    if (!problem) toast.success(`Made a ${categoryLabel(category)} bucket`);
    reload();
    onChanged();
  }

  async function choose(category: string, value: string) {
    const problem = await send(`/budget/categories/${encodeURIComponent(category)}`, "PUT", {
      bucket_id: value === "none" ? null : Number(value),
    });
    setSaveError(problem);
    if (!problem) {
      const bucket = buckets.find((b) => String(b.id) === value);
      toast.success(
        bucket
          ? `${categoryLabel(category)} now comes out of ${bucket.name}`
          : `${categoryLabel(category)} has no bucket now`,
      );
    }
    reload();
    onChanged();
  }

  const items: Record<string, string> = {
    none: "No bucket",
    ...Object.fromEntries(buckets.map((b) => [String(b.id), b.name])),
  };
  // Every spending category, so defaults can be set before there's any spending: the
  // backend's list (biggest spending first), then the rest.
  const rows: CategoryBucket[] | null = data && [
    ...data,
    ...ALL_CATEGORIES.filter(
      (c) => !INCOME_CATEGORIES.includes(c) && !data.some((d) => d.category === c),
    ).map((c) => ({ category: c, bucket_id: null, spent_cents: 0 })),
  ];

  return (
    <Card>
      <CardHeader>
        <CardTitle>Which bucket pays for what</CardTitle>
        <CardDescription>
          Spending comes out of its category&apos;s bucket. This applies to everything since{" "}
          {formatDay(startDate)}, so changing it re-sorts past spending too. To use a different
          bucket for one purchase, open it on the Transactions page. A bucket named like a
          category (say, &ldquo;Transport&rdquo;) is picked for it automatically.
        </CardDescription>
      </CardHeader>
      <CardContent className="text-sm">
        {error && <p className="text-destructive">{error}</p>}
        {rows && (
          <ul className="flex flex-col divide-y">
            {rows.map((c) => (
              <li key={c.category} className="flex flex-wrap items-center gap-x-3 gap-y-1 py-2">
                <span className="flex min-w-40 flex-1 items-center gap-2">
                  <span
                    className="size-2.5 rounded-[3px]"
                    style={{ background: categoryColor(c.category) }}
                  />
                  {categoryLabel(c.category)}
                  {c.spent_cents !== 0 && (
                    <span className="text-muted-foreground tabular">
                      {formatCurrency(c.spent_cents)} spent
                    </span>
                  )}
                </span>
                {c.bucket_id === null && (
                  <Button variant="ghost" size="sm" onClick={() => makeBucket(c.category)}>
                    Make a bucket
                  </Button>
                )}
                <Select
                  items={items}
                  value={c.bucket_id === null ? "none" : String(c.bucket_id)}
                  onValueChange={(v) => choose(c.category, v as string)}
                >
                  <SelectTrigger
                    className={cn("w-48", c.bucket_id === null && c.spent_cents > 0 && "border-destructive")}
                    aria-label={`Bucket for ${categoryLabel(c.category)}`}
                  >
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    {Object.entries(items).map(([v, label]) => (
                      <SelectItem key={v} value={v}>
                        {label}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </li>
            ))}
          </ul>
        )}
        {saveError && <p className="text-destructive">{saveError}</p>}
      </CardContent>
    </Card>
  );
}

// --- Shared pieces ------------------------------------------------------------------------

function NewBucketForm({ onCreated }: { onCreated: () => void }) {
  const [name, setName] = useState("");
  const [type, setType] = useState<"recurring" | "goal">("recurring");
  const [target, setTarget] = useState("");
  const [date, setDate] = useState("");
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const targetCents = parseDollars(target);
  const ok = name.trim() !== "" && (type === "recurring" || targetCents !== null);

  async function create(e: React.FormEvent) {
    e.preventDefault();
    setSaving(true);
    const problem = await send("/buckets", "POST", {
      name,
      type,
      ...(type === "goal" ? { target_amount_cents: targetCents, target_date: date || null } : {}),
    });
    setSaving(false);
    setError(problem);
    if (!problem) {
      toast.success(`Made ${name}`);
      setName("");
      setTarget("");
      setDate("");
      onCreated();
    }
  }

  return (
    <form onSubmit={create} className="flex flex-col gap-3 text-sm">
      <div className="flex flex-wrap items-end gap-3">
        <Label className="flex flex-col items-start gap-1 font-normal">
          Name
          <Input
            value={name}
            onChange={(e) => setName(e.target.value)}
            placeholder={type === "goal" ? "Switch 2" : "Groceries"}
            className="w-48"
          />
        </Label>
        <fieldset className="flex flex-col gap-1">
          <legend className="mb-1">Kind</legend>
          <div className="flex gap-1">
            {(["recurring", "goal"] as const).map((t) => (
              <Button
                key={t}
                type="button"
                size="sm"
                variant={type === t ? "secondary" : "outline"}
                aria-pressed={type === t}
                onClick={() => setType(t)}
              >
                {t === "goal" ? "Goal" : "Recurring"}
              </Button>
            ))}
          </div>
        </fieldset>
      </div>
      {type === "goal" && (
        <div className="flex flex-wrap gap-3">
          <Label className="flex flex-col items-start gap-1 font-normal">
            Target
            <MoneyInput value={target} onChange={setTarget} placeholder="500" />
          </Label>
          <Label className="flex flex-col items-start gap-1 font-normal">
            By (optional)
            <Input type="date" value={date} onChange={(e) => setDate(e.target.value)} className="w-40" />
          </Label>
        </div>
      )}
      <div>
        <Button type="submit" size="sm" disabled={!ok || saving}>
          {saving ? "Adding…" : "Add bucket"}
        </Button>
      </div>
      {error && <p className="text-destructive">{error}</p>}
    </form>
  );
}
