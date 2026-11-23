"use client";

import Link from "next/link";
import { Suspense, useState } from "react";
import { toast } from "sonner";

import { MoneyInput } from "@/components/money-input";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Skeleton } from "@/components/ui/skeleton";
import {
  api,
  send,
  useApi,
  type Account,
  type Bucket,
  type BucketAmount,
  type Budget,
  type IncomeSource,
  type IncomeSourceSuggestion,
  type Paycheck,
  type PaycheckRule,
  type PaycheckSplitSuggestion,
} from "@/lib/api";
import { parseOptionalDollars } from "@/lib/budget";
import { formatCurrency, formatDay } from "@/lib/format";
import { parseDollars } from "@/lib/splits";
import { useAutoSync } from "@/lib/use-auto-sync";
import { cn } from "@/lib/utils";

export default function PaychecksPage() {
  return (
    <Suspense>
      <Paychecks />
    </Suspense>
  );
}

function Paychecks() {
  const { syncKey } = useAutoSync();
  const [changes, setChanges] = useState(0);
  const changed = () => setChanges((c) => c + 1);
  const key = syncKey + changes;
  const { data: budget } = useApi<Budget>("/budget", key);
  const { data: accounts } = useApi<Account[]>("/accounts");
  const { data: paychecks, error } = useApi<Paycheck[]>("/paychecks", key);
  const { data: sources } = useApi<IncomeSource[]>("/income-sources", key);

  const open = budget?.buckets.filter((b) => !b.archived) ?? [];

  return (
    <>
      <div className="flex flex-wrap items-baseline gap-3">
        <h1 className="text-xl font-semibold">Paychecks</h1>
        <Link href="/buckets" className="text-sm text-muted-foreground hover:underline">
          ← Buckets
        </Link>
      </div>
      <p className="max-w-2xl text-sm text-muted-foreground">
        When pay comes in, split it into your buckets. Tell the app what your pay looks like
        once, set up your usual split, and each new paycheck comes with a suggestion you can
        adjust.
      </p>
      {error && <p className="text-sm text-destructive">{error}</p>}

      <Card>
        <CardHeader>
          <CardTitle>Your paychecks</CardTitle>
          <CardDescription>
            {budget?.start_date
              ? `Since your budget started on ${formatDay(budget.start_date)}. Earlier pay was already part of the money you split at the start.`
              : "From the last 90 days. Set up your budget on the Buckets page to start splitting them."}
          </CardDescription>
        </CardHeader>
        <CardContent className="flex flex-col gap-3 text-sm">
          {!paychecks || !sources ? (
            <Skeleton className="h-20" />
          ) : paychecks.length === 0 ? (
            <p className="text-muted-foreground">
              {sources.length === 0
                ? "No paychecks found yet: tell the app where your pay comes from, below."
                : "No paychecks yet since your budget started."}
            </p>
          ) : (
            paychecks.map((p) => (
              <PaycheckRow key={p.transaction_id} paycheck={p} buckets={open} onChanged={changed} />
            ))
          )}
        </CardContent>
      </Card>

      <RulesEditor buckets={open} onChanged={changed} />
      <IncomeSources accounts={accounts ?? []} sources={sources} onChanged={changed} />
    </>
  );
}

// --- One paycheck --------------------------------------------------------------------------

function PaycheckRow({
  paycheck: p,
  buckets,
  onChanged,
}: {
  paycheck: Paycheck;
  buckets: Bucket[];
  onChanged: () => void;
}) {
  const [editing, setEditing] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const nameOf = (id: number) => buckets.find((b) => b.id === id)?.name ?? "an archived bucket";

  async function mark(isPaycheck: boolean | null) {
    const problem = await send(`/paychecks/${p.transaction_id}/mark`, "PUT", {
      is_paycheck: isPaycheck,
    });
    setError(problem);
    if (!problem) {
      onChanged();
      toast.success(
        isPaycheck === null ? "Back to automatic" : isPaycheck ? "Marked as a paycheck" : "Not a paycheck",
      );
    }
  }

  async function notAPaycheck() {
    const giveBack =
      p.split_cents > 0 ? ` Its ${formatCurrency(p.split_cents)} goes back to unassigned.` : "";
    if (window.confirm(`Not a paycheck?${giveBack}`)) await mark(false);
  }

  if (!p.is_paycheck) {
    return (
      <div className="flex flex-wrap items-center justify-between gap-2 rounded-lg border border-dashed p-3 text-muted-foreground">
        <span>
          {formatDay(p.date)} · {p.description} · {formatCurrency(p.deposit_cents)} · marked
          not a paycheck
        </span>
        <Button variant="ghost" size="sm" onClick={() => mark(null)}>
          Undo
        </Button>
      </div>
    );
  }

  const unsplit = p.paycheck_cents - p.split_cents;

  return (
    <section className="flex flex-col gap-2 rounded-lg border p-3">
      <div className="flex flex-wrap items-start justify-between gap-2">
        <div>
          <p className="font-medium">
            {p.description}{" "}
            <span className="tabular">{formatCurrency(p.paycheck_cents)}</span>
          </p>
          <p className="text-muted-foreground">
            {formatDay(p.date)}
            {p.paycheck_cents !== p.deposit_cents &&
              ` · pay part of a ${formatCurrency(p.deposit_cents)} deposit`}
            {p.override && " · marked by you"}
          </p>
        </div>
        <div className="flex items-center gap-1">
          {!p.splittable ? (
            <Badge variant="secondary">Before your budget</Badge>
          ) : p.split_cents === 0 ? (
            <Badge>Not split yet</Badge>
          ) : unsplit > 0 ? (
            <Badge variant="secondary">{formatCurrency(unsplit)} left unassigned</Badge>
          ) : (
            <Badge variant="secondary">Split</Badge>
          )}
          {p.splittable && !editing && (
            <Button size="sm" variant={p.split_cents === 0 ? "default" : "outline"} onClick={() => setEditing(true)}>
              {p.split_cents === 0 ? "Split" : "Change split"}
            </Button>
          )}
          <Button variant="ghost" size="sm" onClick={notAPaycheck}>
            Not a paycheck
          </Button>
        </div>
      </div>
      {p.split.length > 0 && !editing && (
        <p className="text-muted-foreground">
          {p.split.map((s) => `${nameOf(s.bucket_id)} ${formatCurrency(s.amount_cents)}`).join(" · ")}
        </p>
      )}
      {editing && (
        <SplitEditor
          paycheck={p}
          buckets={buckets}
          onDone={() => {
            setEditing(false);
            onChanged();
          }}
          onCancel={() => setEditing(false)}
        />
      )}
      {error && <p className="text-destructive">{error}</p>}
    </section>
  );
}

/** Amounts per bucket for one paycheck: starts from its current split, or the rules'
 * suggestion when it hasn't been split. */
function SplitEditor({
  paycheck: p,
  buckets,
  onDone,
  onCancel,
}: {
  paycheck: Paycheck;
  buckets: Bucket[];
  onDone: () => void;
  onCancel: () => void;
}) {
  const { data: suggestion } = useApi<PaycheckSplitSuggestion>(
    `/paychecks/${p.transaction_id}/suggestion`,
  );
  const [typed, setTyped] = useState<Record<number, string> | null>(null);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  if (!suggestion) return <Skeleton className="h-24" />;

  const toText = (parts: BucketAmount[]) =>
    Object.fromEntries(parts.map((s) => [s.bucket_id, (s.amount_cents / 100).toFixed(2)]));
  const values = typed ?? toText(p.split.length > 0 ? p.split : suggestion.suggested);
  const amounts = buckets.map((b) => parseOptionalDollars(values[b.id] ?? ""));
  const invalid = amounts.some((a) => a === null);
  const left = p.paycheck_cents - amounts.reduce<number>((sum, a) => sum + (a ?? 0), 0);
  const problem = invalid
    ? "Each amount should look like 45 or 45.50"
    : left < 0
      ? `That's ${formatCurrency(-left)} more than the paycheck`
      : null;

  async function save() {
    setSaving(true);
    const parts = buckets
      .map((b, i) => ({ bucket_id: b.id, amount_cents: amounts[i] ?? 0 }))
      .filter((part) => part.amount_cents > 0);
    const failed = await send(`/paychecks/${p.transaction_id}/split`, "PUT", parts);
    setSaving(false);
    setError(failed);
    if (!failed) {
      onDone();
      toast.success(parts.length > 0 ? "Paycheck split into your buckets" : "Split cleared");
    }
  }

  if (buckets.length === 0) {
    return (
      <p className="text-muted-foreground">
        Make some buckets first, on the <Link href="/buckets" className="underline">Buckets</Link> page.
      </p>
    );
  }

  return (
    <div className="flex flex-col gap-2 border-t pt-3">
      <ul className="flex flex-col gap-2">
        {buckets.map((b) => (
          <li key={b.id} className="flex items-center gap-3">
            <Label htmlFor={`split-${p.transaction_id}-${b.id}`} className="min-w-36 flex-1 font-normal">
              {b.name}
            </Label>
            <MoneyInput
              id={`split-${p.transaction_id}-${b.id}`}
              value={values[b.id] ?? ""}
              onChange={(v) => setTyped({ ...values, [b.id]: v })}
            />
          </li>
        ))}
      </ul>
      <p className={cn("tabular", left < 0 && "text-destructive")}>
        Left unassigned: <strong>{formatCurrency(left)}</strong>
      </p>
      {(problem ?? error) && <p className="text-destructive">{problem ?? error}</p>}
      <div className="flex flex-wrap gap-2">
        <Button size="sm" onClick={save} disabled={saving || problem !== null}>
          {saving ? "Saving…" : "Save split"}
        </Button>
        <Button size="sm" variant="outline" onClick={() => setTyped(toText(suggestion.suggested))}>
          Use my usual split
        </Button>
        <Button size="sm" variant="ghost" onClick={onCancel}>
          Cancel
        </Button>
      </div>
    </div>
  );
}

// --- The usual split -----------------------------------------------------------------------

type DraftRule = { bucket: string; kind: "fixed" | "percent"; value: string };

function RulesEditor({ buckets, onChanged }: { buckets: Bucket[]; onChanged: () => void }) {
  const { data: saved, reload } = useApi<PaycheckRule[]>("/paycheck-rules");
  const [draft, setDraft] = useState<DraftRule[] | null>(null);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  if (!saved) return <Skeleton className="h-32 rounded-xl" />;

  const rules: DraftRule[] =
    draft ??
    saved.map((r) => ({
      bucket: String(r.bucket_id),
      kind: r.kind,
      value: r.kind === "fixed" ? (r.amount_cents! / 100).toFixed(2) : String(r.percent),
    }));
  const update = (i: number, change: Partial<DraftRule>) =>
    setDraft(rules.map((r, j) => (j === i ? { ...r, ...change } : r)));
  const move = (i: number, by: number) => {
    const next = [...rules];
    [next[i], next[i + by]] = [next[i + by], next[i]];
    setDraft(next);
  };

  const parsed = rules.map((r) =>
    r.kind === "fixed"
      ? parseDollars(r.value)
      : /^\d+$/.test(r.value.trim()) && Number(r.value) >= 1 && Number(r.value) <= 100
        ? Number(r.value)
        : null,
  );
  const totalPercent = rules.reduce((sum, r, i) => sum + (r.kind === "percent" ? (parsed[i] ?? 0) : 0), 0);
  const problem = rules.some((r) => !r.bucket)
    ? "Pick a bucket for each line"
    : parsed.some((v) => v === null)
      ? "Amounts look like 1500 or 1500.00; percents are whole numbers from 1 to 100"
      : totalPercent > 100
        ? `The percents add up to ${totalPercent}%, over 100%`
        : null;

  async function save() {
    setSaving(true);
    const failed = await send(
      "/paycheck-rules",
      "PUT",
      rules.map((r, i) => ({
        bucket_id: Number(r.bucket),
        kind: r.kind,
        ...(r.kind === "fixed" ? { amount_cents: parsed[i] } : { percent: parsed[i] }),
      })),
    );
    setSaving(false);
    setError(failed);
    if (!failed) {
      setDraft(null);
      reload();
      onChanged();
      toast.success("Paycheck rules saved");
    }
  }

  const items = Object.fromEntries(buckets.map((b) => [String(b.id), b.name]));

  return (
    <Card>
      <CardHeader>
        <CardTitle>Your usual split</CardTitle>
        <CardDescription>
          Each paycheck&apos;s suggestion: fixed amounts come out first, top to bottom, then
          each percent is of what&apos;s left after them. Whatever isn&apos;t covered stays
          unassigned. You can always change a paycheck&apos;s split before saving it.
        </CardDescription>
      </CardHeader>
      <CardContent className="flex flex-col gap-3 text-sm">
        {rules.length === 0 && <p className="text-muted-foreground">No rules yet.</p>}
        <ol className="flex flex-col gap-2">
          {rules.map((r, i) => (
            <li key={i} className="flex flex-wrap items-center gap-2">
              <Select items={items} value={r.bucket} onValueChange={(v) => update(i, { bucket: v as string })}>
                <SelectTrigger className="w-44" aria-label={`Bucket for line ${i + 1}`}>
                  <SelectValue placeholder="Bucket" />
                </SelectTrigger>
                <SelectContent>
                  {buckets.map((b) => (
                    <SelectItem key={b.id} value={String(b.id)}>
                      {b.name}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
              <div className="flex gap-1">
                {(["fixed", "percent"] as const).map((k) => (
                  <Button
                    key={k}
                    type="button"
                    size="sm"
                    variant={r.kind === k ? "secondary" : "outline"}
                    aria-pressed={r.kind === k}
                    onClick={() => update(i, { kind: k, value: "" })}
                  >
                    {k === "fixed" ? "$ amount" : "% of the rest"}
                  </Button>
                ))}
              </div>
              {r.kind === "fixed" ? (
                <MoneyInput value={r.value} onChange={(v) => update(i, { value: v })} aria-label="Amount" />
              ) : (
                <div className="relative w-24">
                  <Input
                    value={r.value}
                    onChange={(e) => update(i, { value: e.target.value })}
                    inputMode="numeric"
                    className="pr-7 text-right tabular"
                    aria-label="Percent"
                  />
                  <span className="pointer-events-none absolute top-1/2 right-2.5 -translate-y-1/2 text-muted-foreground">
                    %
                  </span>
                </div>
              )}
              <div className="flex">
                <Button variant="ghost" size="sm" disabled={i === 0} onClick={() => move(i, -1)} aria-label="Move up">
                  ↑
                </Button>
                <Button
                  variant="ghost"
                  size="sm"
                  disabled={i === rules.length - 1}
                  onClick={() => move(i, 1)}
                  aria-label="Move down"
                >
                  ↓
                </Button>
                <Button
                  variant="ghost"
                  size="sm"
                  onClick={() => setDraft(rules.filter((_, j) => j !== i))}
                  aria-label="Remove line"
                >
                  ×
                </Button>
              </div>
            </li>
          ))}
        </ol>
        <div className="flex flex-wrap gap-2">
          <Button
            size="sm"
            variant="outline"
            disabled={buckets.length === 0}
            onClick={() => setDraft([...rules, { bucket: "", kind: "fixed", value: "" }])}
          >
            Add a line
          </Button>
          {draft !== null && (
            <>
              <Button size="sm" onClick={save} disabled={saving || problem !== null}>
                {saving ? "Saving…" : "Save"}
              </Button>
              <Button size="sm" variant="ghost" onClick={() => setDraft(null)}>
                Cancel
              </Button>
            </>
          )}
        </div>
        {draft !== null && problem && <p className="text-destructive">{problem}</p>}
        {error && <p className="text-destructive">{error}</p>}
      </CardContent>
    </Card>
  );
}

// --- Where pay comes from ------------------------------------------------------------------

function IncomeSources({
  accounts,
  sources,
  onChanged,
}: {
  accounts: Account[];
  sources: IncomeSource[] | null;
  onChanged: () => void;
}) {
  const { data: suggestions, reload } = useApi<IncomeSourceSuggestion[]>(
    "/income-sources/suggestions",
    sources?.length ?? 0,
  );
  const [name, setName] = useState("");
  const [accountId, setAccountId] = useState("");
  const [match, setMatch] = useState("");
  const [error, setError] = useState<string | null>(null);
  const accountName = (id: number) => accounts.find((a) => a.id === id)?.name ?? "…";

  async function add(body: { name: string; account_id: number; match_text: string }) {
    const failed = await send("/income-sources", "POST", body);
    setError(failed);
    if (!failed) {
      setName("");
      setMatch("");
      reload();
      onChanged();
      toast.success(`Added ${body.name} as a paycheck`);
    }
  }

  async function remove(source: IncomeSource) {
    if (!window.confirm(`Stop recognizing "${source.match_text}" as pay?`)) return;
    await api(`/income-sources/${source.id}`, { method: "DELETE" }).catch(() => {});
    reload();
    onChanged();
  }

  const accountItems = Object.fromEntries(accounts.map((a) => [String(a.id), a.name]));

  return (
    <Card>
      <CardHeader>
        <CardTitle>Where your pay comes from</CardTitle>
        <CardDescription>
          A deposit into the account whose description contains the text is a paycheck.
          Anything it gets wrong, fix with &ldquo;Not a paycheck&rdquo;.
        </CardDescription>
      </CardHeader>
      <CardContent className="flex flex-col gap-4 text-sm">
        {sources && sources.length > 0 && (
          <ul className="flex flex-col divide-y">
            {sources.map((s) => (
              <li key={s.id} className="flex items-center justify-between gap-3 py-2">
                <span>
                  <span className="font-medium">{s.name}</span>{" "}
                  <span className="text-muted-foreground">
                    · &ldquo;{s.match_text}&rdquo; into {accountName(s.account_id)}
                  </span>
                </span>
                <Button variant="ghost" size="sm" onClick={() => remove(s)}>
                  Remove
                </Button>
              </li>
            ))}
          </ul>
        )}

        {suggestions && suggestions.length > 0 && (
          <div className="flex flex-col gap-2">
            <p className="font-medium">Looks like pay</p>
            <ul className="flex flex-col gap-2">
              {suggestions.map((s) => (
                <li
                  key={`${s.account_id}-${s.match_text}`}
                  className="flex flex-wrap items-center justify-between gap-2 rounded-lg border border-dashed p-2"
                >
                  <span>
                    &ldquo;{s.match_text}&rdquo; into {accountName(s.account_id)}
                    <span className="text-muted-foreground">
                      {" "}
                      · {s.count} times in 90 days, last {formatCurrency(s.last_amount_cents)} on{" "}
                      {formatDay(s.last_date)}
                    </span>
                  </span>
                  <Button
                    size="sm"
                    onClick={() =>
                      add({ name: s.match_text, account_id: s.account_id, match_text: s.match_text })
                    }
                  >
                    This is my pay
                  </Button>
                </li>
              ))}
            </ul>
          </div>
        )}

        <form
          className="flex flex-wrap items-end gap-3"
          onSubmit={(e) => {
            e.preventDefault();
            add({ name: name || match, account_id: Number(accountId), match_text: match });
          }}
        >
          <Label className="flex flex-col items-start gap-1 font-normal">
            Description contains
            <Input value={match} onChange={(e) => setMatch(e.target.value)} placeholder="Rippling" className="w-44" />
          </Label>
          <Label className="flex flex-col items-start gap-1 font-normal">
            Into
            <Select items={accountItems} value={accountId} onValueChange={(v) => setAccountId(v as string)}>
              <SelectTrigger className="w-48" aria-label="Account the pay goes into">
                <SelectValue placeholder="Account" />
              </SelectTrigger>
              <SelectContent>
                {accounts.map((a) => (
                  <SelectItem key={a.id} value={String(a.id)}>
                    {a.name}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </Label>
          <Label className="flex flex-col items-start gap-1 font-normal">
            Name (optional)
            <Input value={name} onChange={(e) => setName(e.target.value)} placeholder="Internship pay" className="w-44" />
          </Label>
          <Button type="submit" size="sm" disabled={match.trim().length < 2 || !accountId}>
            Add
          </Button>
        </form>
        {error && <p className="text-destructive">{error}</p>}
      </CardContent>
    </Card>
  );
}
