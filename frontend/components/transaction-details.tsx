"use client";

import { useState } from "react";

import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Sheet, SheetContent, SheetDescription, SheetHeader, SheetTitle } from "@/components/ui/sheet";
import { Skeleton } from "@/components/ui/skeleton";
import { api, query, useApi, type Account, type Transaction, type TransactionPage } from "@/lib/api";
import { categoryColor, categoryLabel } from "@/lib/categories";
import { addDays, formatCurrency, formatDay, parseDate } from "@/lib/format";
import { foreignAmount } from "@/lib/transactions";
import { cn } from "@/lib/utils";

/**
 * A side panel with everything known about one transaction, where it can also be renamed,
 * and money in can be linked to the purchase it pays back. `onSelect` opens another
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
          {!t.is_transfer && t.amount_cents > 0 && (
            <Row label="Pays back">
              <PaysBack t={t} accounts={accounts} onSelect={onSelect} onSaved={saved} />
            </Row>
          )}
          {!t.is_transfer && t.amount_cents < 0 && (
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
      </div>
    </>
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
 * Pick the purchase a payback is for: purchases (money out), newest first. A friend often
 * pays the same night, before the card posts the charge a day or two later, so the list
 * starts a week after the payback. A search looks at every date: you know what you want.
 */
function PurchasePicker({
  payback,
  busy,
  onPick,
  onCancel,
}: {
  payback: Transaction;
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
          const fits = left >= payback.amount_cents;
          return (
            <li key={p.id}>
              <button
                type="button"
                disabled={busy || !fits}
                onClick={() => onPick(p.id)}
                className="flex w-full items-baseline justify-between gap-2 rounded-md px-2 py-1.5 text-left hover:bg-muted disabled:opacity-50 disabled:hover:bg-transparent"
                title={fits ? undefined : `Only ${formatCurrency(left)} of it is left to pay back`}
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
