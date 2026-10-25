"use client";

import { useState } from "react";

import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Sheet, SheetContent, SheetDescription, SheetHeader, SheetTitle } from "@/components/ui/sheet";
import { Skeleton } from "@/components/ui/skeleton";
import { api, useApi, type Account, type Transaction } from "@/lib/api";
import { categoryColor, categoryLabel } from "@/lib/categories";
import { formatCurrency, formatDay, parseDate } from "@/lib/format";
import { foreignAmount } from "@/lib/transactions";
import { cn } from "@/lib/utils";

/**
 * A side panel with everything known about one transaction, where it can also be renamed.
 * `onSelect` opens another transaction in the panel (the other side of a transfer).
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
            ) : (
              <span className="flex items-center gap-2">
                <span
                  className="size-2.5 rounded-[3px]"
                  style={{ background: categoryColor(t.category) }}
                />
                {categoryLabel(t.category)}
                <span className="text-muted-foreground">
                  · {t.category_source === "manual" ? "set by you" : "from a rule"}
                </span>
              </span>
            )}
          </Row>
          <Row label="Transfer">
            {t.is_transfer ? (
              <>
                Yes, money moving between my accounts
                <span className="text-muted-foreground">
                  {" "}
                  · {t.transfer_source === "manual" ? "marked by you" : "detected automatically"}
                </span>
                {t.transfer_pair_id !== null && (
                  <TransferPartner id={t.transfer_pair_id} accounts={accounts} onSelect={onSelect} />
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

function TransferPartner({
  id,
  accounts,
  onSelect,
}: {
  id: number;
  accounts: Account[] | null;
  onSelect: (id: number) => void;
}) {
  const { data: partner } = useApi<Transaction>(`/transactions/${id}`);
  if (!partner) return null;
  const account = accounts?.find((a) => a.id === partner.account_id);
  return (
    <button
      type="button"
      onClick={() => onSelect(partner.id)}
      className="mt-2 block w-full rounded-md border px-3 py-2 text-left hover:bg-muted"
    >
      <span className="block text-xs text-muted-foreground">Other side</span>
      {partner.description} · {formatCurrency(partner.amount_cents)}
      <span className="block text-xs text-muted-foreground">
        {formatDay(partner.date)} · {account?.name}
      </span>
    </button>
  );
}

function RenameForm({ t, onSaved }: { t: Transaction; onSaved: () => void }) {
  const [name, setName] = useState(t.description);
  const [all, setAll] = useState(t.description_source === "rule");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function patch(body: object) {
    setBusy(true);
    setError(null);
    try {
      await api(`/transactions/${t.id}`, {
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
