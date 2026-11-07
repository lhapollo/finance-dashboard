"use client";

import { useState } from "react";

import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Sheet, SheetContent, SheetDescription, SheetHeader, SheetTitle } from "@/components/ui/sheet";
import { Skeleton } from "@/components/ui/skeleton";
import {
  api,
  query,
  useApi,
  type Account,
  type Transaction,
  type TransactionPage,
} from "@/lib/api";
import { ALL_CATEGORIES, categoryColor, categoryLabel } from "@/lib/categories";
import { checkSplit, parseDollars } from "@/lib/splits";
import { addDays, formatCurrency, formatDay, parseDate } from "@/lib/format";
import { foreignAmount } from "@/lib/transactions";
import { cn } from "@/lib/utils";

/**
 * A side panel with everything known about one transaction, where it can also be renamed,
 * split into parts, and money in can be linked to the purchase it pays back. `onSelect` opens another
 * transaction in the panel (the other side of a transfer, a payback or its purchase).
 */
export function TransactionDetails({
  transactionId,
  onClose,
  onSelect,
  onChanged,
}: {
  transactionId: number | null;
  onClose: () => void;
  onSelect: (id: number) => void;
  onChanged: () => void;
}) {
  return (
    <Sheet open={transactionId !== null} onOpenChange={(open) => !open && onClose()}>
      <SheetContent className="w-full overflow-y-auto sm:max-w-md">
        {transactionId !== null && (
          <Details
            key={transactionId}
            id={transactionId}
            onSelect={onSelect}
            onChanged={onChanged}
          />
        )}
      </SheetContent>
    </Sheet>
  );
}

function Details({
  id,
  onSelect,
  onChanged,
}: {
  id: number;
  onSelect: (id: number) => void;
  onChanged: () => void;
}) {
  const { data: t, error, reload } = useApi<Transaction>(`/transactions/${id}`);
  const { data: accounts } = useApi<Account[]>("/accounts");
  // While the split editor is open, the whole-transaction payback and reimbursable rows
  // are hidden: the parts decide those.
  const [splitting, setSplitting] = useState(false);

  if (error) return <p className="p-4 text-sm text-destructive">{error}</p>;
  if (!t) {
    return (
      <div className="flex flex-col gap-3 p-4">
        <Skeleton className="h-6 w-2/3" />
        <Skeleton className="h-10 w-1/3" />
        <Skeleton className="h-32 w-full" />
      </div>
    );
  }

  const account = accounts?.find((a) => a.id === t.account_id);
  const foreign = foreignAmount(t.raw_description);
  const saved = () => {
    reload();
    onChanged();
  };

  return (
    <>
      <SheetHeader>
        <SheetTitle className="pr-6 text-lg">{t.description}</SheetTitle>
        <SheetDescription>
          {parseDate(t.date).toLocaleDateString("en-CA", { dateStyle: "full" })}
        </SheetDescription>
      </SheetHeader>

      <div className="flex flex-col gap-6 px-4 pb-6">
        <div
          className={cn(
            "text-3xl font-semibold tracking-tight",
            t.amount_cents > 0 && "text-positive",
          )}
        >
          {formatCurrency(t.amount_cents)}
          <span className="ml-2 align-middle text-sm font-normal text-muted-foreground">
            {t.amount_cents < 0 ? "money out" : "money in"}
          </span>
        </div>

        {/* Keyed on the saved name so the form resets after each save. */}
        <RenameForm key={`${t.description}|${t.description_source}`} t={t} onSaved={saved} />

        <dl className="grid grid-cols-[8rem_1fr] gap-x-4 gap-y-3 text-sm">
          <Row label="From the bank">
            <span className="font-mono text-xs break-all">{t.raw_description}</span>
          </Row>
          {foreign && (
            <Row label="Original amount">
              {foreign.amount} {foreign.currency}
              <span className="text-muted-foreground"> at {foreign.rate} CAD per {foreign.currency}</span>
            </Row>
          )}
          <Row label="Account">{account?.name ?? "…"}</Row>
          <Row label="Category">
            {t.is_transfer ? (
              <span className="text-muted-foreground">Not counted (transfer)</span>
            ) : t.splits.length > 0 ? (
              <span className="text-muted-foreground">Split into {t.splits.length} parts, below</span>
            ) : t.reimbursable ? (
              <span className="text-muted-foreground">
                Not counted ({categoryLabel(t.category)}, but someone is paying it back)
              </span>
            ) : (
              <span className="flex items-center gap-2">
                <span
                  className="size-2.5 rounded-[3px]"
                  style={{ background: categoryColor(t.counted_category) }}
                />
                {categoryLabel(t.counted_category)}
                <span className="text-muted-foreground">
                  ·{" "}
                  {t.reimburses_id !== null
                    ? "same as the purchase it pays back"
                    : t.category_source === "manual"
                      ? "set by you"
                      : "from a rule"}
                </span>
              </span>
            )}
          </Row>
          {!t.is_transfer && t.amount_cents > 0 && t.splits.length === 0 && !splitting && (
            <Row label="Pays back">
              <PaysBack t={t} accounts={accounts} onSelect={onSelect} onSaved={saved} />
            </Row>
          )}
          {!t.is_transfer && t.amount_cents < 0 && t.splits.length === 0 && !splitting && (
            <Row label="Reimbursable">
              <ReimbursableToggle t={t} onSaved={saved} />
            </Row>
          )}
          {t.reimbursement_ids.length > 0 && (
            <Row label="Paid back">
              {formatCurrency(t.reimbursed_cents)} of {formatCurrency(-t.amount_cents)}
              <span className="text-muted-foreground">
                {" "}
                · {t.reimbursable ? "still owed" : "your share"}{" "}
                {formatCurrency(-t.amount_cents - t.reimbursed_cents)}
              </span>
              {t.reimbursement_ids.map((rid) => (
                <LinkedTransaction
                  key={rid}
                  id={rid}
                  caption="Payback"
                  accounts={accounts}
                  onSelect={onSelect}
                />
              ))}
            </Row>
          )}
          <Row label="Transfer">
            {t.is_transfer ? (
              <>
                Yes, money moving between my accounts
                <span className="text-muted-foreground">
                  {" "}
                  · {t.transfer_source === "manual" ? "marked by you" : "detected automatically"}
                </span>
                {t.transfer_pair_id !== null && (
                  <LinkedTransaction
                    id={t.transfer_pair_id}
                    caption="Other side"
                    accounts={accounts}
                    onSelect={onSelect}
                  />
                )}
              </>
            ) : (
              "No"
            )}
          </Row>
          <Row label="Imported">
            {new Date(t.imported_at).toLocaleString("en-CA", {
              dateStyle: "medium",
              timeStyle: "short",
            })}
          </Row>
        </dl>

        {canSplit(t) && (
          <SplitSection
            t={t}
            accounts={accounts}
            editing={splitting}
            setEditing={setSplitting}
            onSelect={onSelect}
            onSaved={saved}
          />
        )}
      </div>
    </>
  );
}

/** Transfers, reimbursable purchases and anything linked to a payback can't be split. */
function canSplit(t: Transaction) {
  return (
    !t.is_transfer &&
    !t.reimbursable &&
    t.reimburses_id === null &&
    t.reimbursement_ids.length === 0
  );
}

function Row({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <>
      <dt className="text-muted-foreground">{label}</dt>
      <dd className="min-w-0">{children}</dd>
    </>
  );
}

/** A button showing another transaction (the other side of a transfer, a payback, the
 * purchase a payback is for) that opens it in the panel. */
function LinkedTransaction({
  id,
  caption,
  accounts,
  onSelect,
}: {
  id: number;
  caption: string;
  accounts: Account[] | null;
  onSelect: (id: number) => void;
}) {
  const { data: other } = useApi<Transaction>(`/transactions/${id}`);
  if (!other) return null;
  const account = accounts?.find((a) => a.id === other.account_id);
  return (
    <button
      type="button"
      onClick={() => onSelect(other.id)}
      className="mt-2 block w-full rounded-md border px-3 py-2 text-left hover:bg-muted"
    >
      <span className="block text-xs text-muted-foreground">{caption}</span>
      {other.description} · {formatCurrency(other.amount_cents)}
      <span className="block text-xs text-muted-foreground">
        {formatDay(other.date)} · {account?.name}
      </span>
    </button>
  );
}

/** Sends a PATCH for transaction `id`, tracking busy and error state for a form. */
function usePatch(id: number, onSaved: () => void) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function patch(body: object) {
    setBusy(true);
    setError(null);
    try {
      await api(`/transactions/${id}`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      });
      onSaved();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }

  return { patch, busy, error };
}

/** On money out: whether someone (work, a friend) will pay all of it back. */
function ReimbursableToggle({ t, onSaved }: { t: Transaction; onSaved: () => void }) {
  const { patch, busy, error } = usePatch(t.id, onSaved);
  const owed = -t.amount_cents - t.reimbursed_cents;

  return (
    <>
      <Label className="flex items-start gap-2 font-normal">
        <Checkbox
          checked={t.reimbursable}
          disabled={busy}
          onCheckedChange={(reimbursable) => patch({ reimbursable })}
          className="mt-0.5"
        />
        <span>Someone will pay all of this back, so it isn’t my spending</span>
      </Label>
      {t.reimbursement_status === "waiting" && (
        <p className="mt-1 text-xs text-muted-foreground">
          Waiting for {formatCurrency(owed)}. When it arrives, open the payment and link it to
          this purchase.
        </p>
      )}
      {t.reimbursement_status === "received" && (
        <p className="mt-1 text-xs text-positive">Paid back in full.</p>
      )}
      {error && <p className="mt-1 text-xs text-destructive">{error}</p>}
    </>
  );
}

/** On money in: the purchase it pays back, or a way to pick one. */
function PaysBack({
  t,
  accounts,
  onSelect,
  onSaved,
}: {
  t: Transaction;
  accounts: Account[] | null;
  onSelect: (id: number) => void;
  onSaved: () => void;
}) {
  const { patch, busy, error } = usePatch(t.id, onSaved);
  const [picking, setPicking] = useState(false);

  if (t.reimburses_id !== null) {
    return (
      <>
        <LinkedTransaction id={t.reimburses_id} caption="Purchase" accounts={accounts} onSelect={onSelect} />
        <button
          type="button"
          className="mt-1.5 text-xs text-muted-foreground underline"
          disabled={busy}
          onClick={() => patch({ reimburses_id: null })}
        >
          Unlink
        </button>
        {error && <p className="text-xs text-destructive">{error}</p>}
      </>
    );
  }

  return (
    <>
      <span className="text-muted-foreground">Nothing linked</span>
      {!picking ? (
        <button type="button" className="ml-2 underline" onClick={() => setPicking(true)}>
          Link to a purchase
        </button>
      ) : (
        <PurchasePicker
          payback={t}
          busy={busy}
          onPick={(purchaseId) => patch({ reimburses_id: purchaseId })}
          onCancel={() => setPicking(false)}
        />
      )}
      {error && <p className="mt-1 text-xs text-destructive">{error}</p>}
    </>
  );
}

/**
 * Pick the purchase a payback (or a part of one) is for: purchases (money out), newest first. A friend often
 * pays the same night, before the card posts the charge a day or two later, so the list
 * starts a week after the payback. A search looks at every date: you know what you want.
 */
function PurchasePicker({
  payback,
  busy,
  onPick,
  onCancel,
}: {
  payback: Pick<Transaction, "date" | "amount_cents">;
  busy: boolean;
  onPick: (purchaseId: number) => void;
  onCancel: () => void;
}) {
  const [search, setSearch] = useState("");
  const searching = search.trim() !== "";
  const { data, error } = useApi<TransactionPage>(
    `/transactions${query({
      money: "out",
      is_transfer: false,
      end: searching ? undefined : addDays(payback.date, 8),
      search: search.trim(),
      limit: 8,
    })}`,
  );

  return (
    <div className="mt-2 flex flex-col gap-2 rounded-lg border p-2">
      <Input
        autoFocus
        placeholder="Search purchases, e.g. pizza"
        value={search}
        onChange={(e) => setSearch(e.target.value)}
        maxLength={100}
        aria-label="Search purchases"
      />
      {error && <p className="text-xs text-destructive">{error}</p>}
      {data?.items.length === 0 && (
        <p className="px-1 text-xs text-muted-foreground">No purchases match.</p>
      )}
      <ul className="flex flex-col">
        {data?.items.map((p) => {
          // What's still owed on it, counting other paybacks (but not this one, if relinking).
          const left = -p.amount_cents - p.reimbursed_cents;
          const split = p.splits.length > 0; // a split purchase can't be paid back
          const fits = !split && left >= payback.amount_cents;
          return (
            <li key={p.id}>
              <button
                type="button"
                disabled={busy || !fits}
                onClick={() => onPick(p.id)}
                className="flex w-full items-baseline justify-between gap-2 rounded-md px-2 py-1.5 text-left hover:bg-muted disabled:opacity-50 disabled:hover:bg-transparent"
                title={
                  split
                    ? "It's split into parts, so it can't be paid back"
                    : fits
                      ? undefined
                      : `Only ${formatCurrency(left)} of it is left to pay back`
                }
              >
                <span className="min-w-0">
                  <span className="block truncate">{p.description}</span>
                  <span className="block text-xs text-muted-foreground">
                    {formatDay(p.date)} · {categoryLabel(p.category)}
                    {p.reimbursed_cents > 0 && ` · ${formatCurrency(p.reimbursed_cents)} back already`}
                  </span>
                </span>
                <span className="shrink-0 tabular">{formatCurrency(p.amount_cents)}</span>
              </button>
            </li>
          );
        })}
      </ul>
      <Button variant="ghost" size="sm" className="self-start" onClick={onCancel}>
        Cancel
      </Button>
    </div>
  );
}

function RenameForm({ t, onSaved }: { t: Transaction; onSaved: () => void }) {
  const [name, setName] = useState(t.description);
  const [all, setAll] = useState(t.description_source === "rule");
  const { patch, busy, error } = usePatch(t.id, onSaved);

  const unchanged = name.trim() === t.description && all === (t.description_source === "rule");

  return (
    <form
      className="flex flex-col gap-3 rounded-lg border p-3"
      onSubmit={(e) => {
        e.preventDefault();
        patch({ description: name, rename_all: all });
      }}
    >
      <Label htmlFor="txn-name">Name</Label>
      <div className="flex gap-2">
        <Input id="txn-name" value={name} onChange={(e) => setName(e.target.value)} maxLength={500} />
        <Button type="submit" disabled={busy || !name.trim() || unchanged}>
          {busy ? "Saving…" : "Save"}
        </Button>
      </div>
      <Label className="flex items-start gap-2 font-normal">
        <Checkbox checked={all} onCheckedChange={(checked) => setAll(checked)} className="mt-0.5" />
        <span>
          Rename every “{t.cleaned_description}” transaction, including future imports
        </span>
      </Label>
      {t.description_source !== "auto" && (
        <p className="text-xs text-muted-foreground">
          {t.description_source === "rule"
            ? `Renamed by a rule from “${t.cleaned_description}”. `
            : "You renamed just this one. "}
          <button
            type="button"
            className="underline"
            disabled={busy}
            onClick={() =>
              // Undoing a rule removes it for every transaction from this merchant.
              patch(
                t.description_source === "rule"
                  ? { description: t.cleaned_description, rename_all: true }
                  : { description: null },
              )
            }
          >
            {t.description_source === "rule" ? "Remove rule" : "Undo rename"}
          </button>
        </p>
      )}
      {error && <p className="text-xs text-destructive">{error}</p>}
    </form>
  );
}

type DraftPart = { amount: string; category: string; reimburses_id: number | null };

/** The parts of a split transaction, or a button to split it, and an editor for both. */
function SplitSection({
  t,
  accounts,
  editing,
  setEditing,
  onSelect,
  onSaved,
}: {
  t: Transaction;
  accounts: Account[] | null;
  editing: boolean;
  setEditing: (editing: boolean) => void;
  onSelect: (id: number) => void;
  onSaved: () => void;
}) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function save(parts: { amount_cents: number; category: string; reimburses_id: number | null }[]) {
    setBusy(true);
    setError(null);
    try {
      await api(`/transactions/${t.id}/splits`, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(parts),
      });
      setEditing(false);
      onSaved();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }

  if (editing) {
    return (
      <SplitEditor
        t={t}
        accounts={accounts}
        busy={busy}
        error={error}
        onSave={save}
        onCancel={() => {
          setEditing(false);
          setError(null);
        }}
      />
    );
  }

  if (t.splits.length === 0) {
    return (
      <div className="rounded-lg border p-3 text-sm">
        <p className="text-muted-foreground">
          {t.amount_cents > 0
            ? "Part of this is something else, like a reimbursement in a paycheck?"
            : "Part of this belongs in another category, like household items at Costco?"}
        </p>
        <Button variant="outline" size="sm" className="mt-2" onClick={() => setEditing(true)}>
          Split this transaction
        </Button>
      </div>
    );
  }

  return (
    <div className="flex flex-col gap-2 rounded-lg border p-3 text-sm">
      <p className="font-medium">Split into {t.splits.length} parts</p>
      <ul className="flex flex-col gap-1.5">
        {t.splits.map((s) => (
          <li key={s.id}>
            <span className="flex items-center justify-between gap-2">
              <span className="flex items-center gap-2">
                <span
                  className="size-2.5 rounded-[3px]"
                  style={{ background: categoryColor(s.counted_category) }}
                />
                {categoryLabel(s.counted_category)}
                {s.reimburses_id !== null && (
                  <span className="text-muted-foreground">· pays back a purchase</span>
                )}
              </span>
              <span className="tabular">{formatCurrency(s.amount_cents)}</span>
            </span>
            {s.reimburses_id !== null && (
              <LinkedTransaction
                id={s.reimburses_id}
                caption="Purchase"
                accounts={accounts}
                onSelect={onSelect}
              />
            )}
          </li>
        ))}
      </ul>
      <div className="flex gap-2">
        <Button variant="outline" size="sm" onClick={() => setEditing(true)} disabled={busy}>
          Edit split
        </Button>
        <Button variant="ghost" size="sm" onClick={() => save([])} disabled={busy}>
          Remove split
        </Button>
      </div>
      {error && <p className="text-xs text-destructive">{error}</p>}
    </div>
  );
}

const CATEGORY_ITEMS = Object.fromEntries(ALL_CATEGORIES.map((c) => [c, categoryLabel(c)]));

function SplitEditor({
  t,
  accounts,
  busy,
  error,
  onSave,
  onCancel,
}: {
  t: Transaction;
  accounts: Account[] | null;
  busy: boolean;
  error: string | null;
  onSave: (parts: { amount_cents: number; category: string; reimburses_id: number | null }[]) => void;
  onCancel: () => void;
}) {
  const dollars = (cents: number) => (Math.abs(cents) / 100).toFixed(2);
  const [parts, setParts] = useState<DraftPart[]>(() =>
    t.splits.length > 0
      ? t.splits.map((s) => ({
          amount: dollars(s.amount_cents),
          category: s.category,
          reimburses_id: s.reimburses_id,
        }))
      : [
          // Start with the whole amount in the first part; lowering it frees up the rest.
          { amount: dollars(t.amount_cents), category: t.category, reimburses_id: null },
          { amount: "", category: t.category, reimburses_id: null },
        ],
  );
  const [picking, setPicking] = useState<number | null>(null); // which part picks a purchase
  const { leftCents, problem } = checkSplit(
    t.amount_cents,
    parts.map((p) => p.amount),
  );
  const sign = t.amount_cents < 0 ? -1 : 1;

  const update = (i: number, change: Partial<DraftPart>) =>
    setParts((ps) => ps.map((p, j) => (j === i ? { ...p, ...change } : p)));

  return (
    <form
      className="flex flex-col gap-3 rounded-lg border p-3 text-sm"
      onSubmit={(e) => {
        e.preventDefault();
        if (problem) return;
        onSave(
          parts.map((p) => ({
            amount_cents: sign * parseDollars(p.amount)!,
            category: p.category,
            reimburses_id: p.reimburses_id,
          })),
        );
      }}
    >
      <p className="font-medium">
        Split {formatCurrency(t.amount_cents)} into parts
      </p>
      {parts.map((p, i) => (
        <div key={i} className="flex flex-col gap-1.5 rounded-md bg-muted/50 p-2">
          <div className="flex items-center gap-2">
            <span className="text-muted-foreground">$</span>
            <Input
              value={p.amount}
              onChange={(e) => update(i, { amount: e.target.value })}
              inputMode="decimal"
              placeholder="0.00"
              className="w-28"
              aria-label={`Amount of part ${i + 1}`}
            />
            {p.reimburses_id === null ? (
              <Select
                items={{ ...CATEGORY_ITEMS, [p.category]: categoryLabel(p.category) }}
                value={p.category}
                onValueChange={(category) => category && update(i, { category })}
              >
                <SelectTrigger size="sm" className="min-w-0 flex-1" aria-label={`Category of part ${i + 1}`}>
                  <span
                    className="size-2 shrink-0 rounded-[2px]"
                    style={{ background: categoryColor(p.category) }}
                  />
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  {Object.entries(CATEGORY_ITEMS).map(([value, label]) => (
                    <SelectItem key={value} value={value}>
                      {label}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            ) : (
              <span className="flex-1 text-xs text-muted-foreground">
                Counts as the purchase’s category
              </span>
            )}
            {parts.length > 2 && (
              <Button
                type="button"
                variant="ghost"
                size="xs"
                onClick={() => setParts((ps) => ps.filter((_, j) => j !== i))}
                aria-label={`Remove part ${i + 1}`}
              >
                ×
              </Button>
            )}
          </div>
          {p.amount.trim() === "" && leftCents > 0 && (
            <button
              type="button"
              className="self-start text-xs underline"
              onClick={() => update(i, { amount: dollars(leftCents) })}
            >
              Use the rest ({formatCurrency(leftCents)})
            </button>
          )}
          {t.amount_cents > 0 &&
            (p.reimburses_id !== null ? (
              <div>
                <LinkedTransaction
                  id={p.reimburses_id}
                  caption="Pays back"
                  accounts={accounts}
                  onSelect={() => {}}
                />
                <button
                  type="button"
                  className="mt-1 text-xs text-muted-foreground underline"
                  onClick={() => update(i, { reimburses_id: null })}
                >
                  Unlink
                </button>
              </div>
            ) : picking === i ? (
              <PurchasePicker
                payback={{ date: t.date, amount_cents: parseDollars(p.amount) ?? 0 }}
                busy={busy}
                onPick={(purchaseId) => {
                  update(i, { reimburses_id: purchaseId });
                  setPicking(null);
                }}
                onCancel={() => setPicking(null)}
              />
            ) : (
              <button
                type="button"
                className="self-start text-xs underline"
                onClick={() => setPicking(i)}
              >
                This part pays back a purchase
              </button>
            ))}
        </div>
      ))}
      <Button
        type="button"
        variant="ghost"
        size="sm"
        className="self-start"
        onClick={() =>
          setParts((ps) => [...ps, { amount: "", category: t.category, reimburses_id: null }])
        }
      >
        + Add a part
      </Button>
      <p className={cn("text-xs", problem ? "text-muted-foreground" : "text-positive")}>
        {problem ?? "Adds up"}
      </p>
      <div className="flex gap-2">
        <Button type="submit" size="sm" disabled={busy || problem !== null}>
          {busy ? "Saving…" : "Save split"}
        </Button>
        <Button type="button" variant="ghost" size="sm" onClick={onCancel} disabled={busy}>
          Cancel
        </Button>
      </div>
      {error && <p className="text-xs text-destructive">{error}</p>}
    </form>
  );
}
