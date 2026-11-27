"use client";

import { ArrowDownIcon, ArrowUpIcon, StickyNoteIcon } from "lucide-react";
import { useState } from "react";
import { toast } from "sonner";

import { TransactionDetails } from "@/components/transaction-details";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Skeleton } from "@/components/ui/skeleton";
import { Switch } from "@/components/ui/switch";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { api, query, useApi, type Transaction, type TransactionPage } from "@/lib/api";
import { ALL_CATEGORIES, categoryColor, categoryLabel } from "@/lib/categories";
import { formatCurrency, formatDay } from "@/lib/format";
import { pageIndex } from "@/lib/transactions";
import { cn } from "@/lib/utils";

export type TransactionFilters = {
  account_id?: number;
  category?: string;
  money?: "in" | "out";
  is_transfer?: boolean; // false hides transfers
  reimbursable?: boolean; // true shows only purchases someone will pay back
  bucket_id?: number; // spending out of this bucket since the budget started
  unbucketed?: boolean; // true: spending since then that no bucket covers
  start?: string;
  end?: string;
  search?: string;
  order?: SortOrder;
};

export type SortOrder = "desc" | "asc"; // newest first / oldest first

const CATEGORY_ITEMS = Object.fromEntries(ALL_CATEGORIES.map((c) => [c, categoryLabel(c)]));

/**
 * Transactions, newest first, with the category and the transfer flag editable in place.
 * A payback (money in linked to a purchase) shows the purchase's category instead.
 * An edit is saved straight away and locks that field against the rules. `onEdited` lets
 * the page refresh totals that the edit changed.
 */
export function TransactionsTable({
  filters = {},
  pageSize = 25,
  paged = true,
  onEdited,
  onOrderChange,
  refreshKey = 0,
}: {
  filters?: TransactionFilters;
  pageSize?: number;
  paged?: boolean;
  onEdited?: () => void;
  /** Bump to reload, e.g. after a bank sync. */
  refreshKey?: number;
  /** When given, the Date header becomes a button that flips the sort order. */
  onOrderChange?: (order: SortOrder) => void;
}) {
  const [page, setPage] = useState(0);
  // Back to page 1 whenever the filters change. (Adjusting state during render is React's
  // recommended way to reset state on a prop change, rather than an effect.)
  const filterKey = JSON.stringify(filters);
  const [lastFilterKey, setLastFilterKey] = useState(filterKey);
  if (filterKey !== lastFilterKey) {
    setLastFilterKey(filterKey);
    setPage(0);
  }

  const { data, error, reload } = useApi<TransactionPage>(
    `/transactions${query({ ...filters, limit: pageSize, offset: page * pageSize })}`,
    refreshKey,
  );
  const [saving, setSaving] = useState<number | null>(null);
  const [openId, setOpenId] = useState<number | null>(null);
  const [saveError, setSaveError] = useState<string | null>(null);

  async function save(t: Transaction, change: { category?: string; is_transfer?: boolean }) {
    setSaving(t.id);
    setSaveError(null);
    try {
      await api(`/transactions/${t.id}`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(change),
      });
      reload();
      onEdited?.();
      toast.success(
        change.category !== undefined
          ? `${t.description} → ${categoryLabel(change.category)}`
          : change.is_transfer
            ? `${t.description} is a transfer now, so it's not counted`
            : `${t.description} counts again`,
      );
    } catch (e) {
      setSaveError(`Couldn't save "${t.description}": ${(e as Error).message}`);
    } finally {
      setSaving(null);
    }
  }

  if (error) return <p className="text-sm text-destructive">{error}</p>;
  if (!data) {
    return (
      <div className="flex flex-col gap-2">
        {Array.from({ length: 6 }, (_, i) => (
          <Skeleton key={i} className="h-9 w-full" />
        ))}
      </div>
    );
  }

  const pages = Math.max(1, Math.ceil(data.total / pageSize));

  return (
    <div className="flex flex-col gap-3">
      {saveError && <p className="text-sm text-destructive">{saveError}</p>}
      <Table>
        <TableHeader>
          <TableRow>
            <TableHead
              className="w-24"
              aria-sort={(filters.order ?? "desc") === "desc" ? "descending" : "ascending"}
            >
              {onOrderChange ? (
                <button
                  type="button"
                  onClick={() => onOrderChange(filters.order === "asc" ? "desc" : "asc")}
                  className="-ml-1 flex items-center gap-1 rounded px-1 hover:bg-muted"
                  title={filters.order === "asc" ? "Oldest first: click for newest first" : "Newest first: click for oldest first"}
                >
                  Date
                  {filters.order === "asc" ? (
                    <ArrowUpIcon className="size-3.5" />
                  ) : (
                    <ArrowDownIcon className="size-3.5" />
                  )}
                </button>
              ) : (
                "Date"
              )}
            </TableHead>
            <TableHead>Description</TableHead>
            <TableHead className="w-44">Category</TableHead>
            <TableHead className="w-28 text-right">Amount</TableHead>
            <TableHead className="w-24 text-center">Transfer</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {data.items.length === 0 && (
            <TableRow>
              <TableCell colSpan={5} className="py-8 text-center text-muted-foreground">
                No transactions match.
              </TableCell>
            </TableRow>
          )}
          {data.items.map((t) => (
            // Every row the height of the category dropdown, so plain-text rows match.
            <TableRow key={t.id} className={cn("h-11", saving === t.id && "opacity-60")}>
              <TableCell className="text-muted-foreground tabular">{formatDay(t.date)}</TableCell>
              <TableCell className="max-w-64">
                {/* Opens the details panel; the bank's exact text (and any note) shows on hover. */}
                <button
                  type="button"
                  onClick={() => setOpenId(t.id)}
                  title={t.note ? `${t.raw_description}\n\nNote: ${t.note}` : t.raw_description}
                  className="flex max-w-full items-center gap-1.5 text-left hover:underline"
                >
                  <span className="truncate">{t.description}</span>
                  {t.note && (
                    <StickyNoteIcon className="size-3.5 shrink-0 text-muted-foreground" aria-label="Has a note" />
                  )}
                </button>
              </TableCell>
              <TableCell>
                {t.is_transfer ? (
                  <span className="text-xs text-muted-foreground">Not counted</span>
                ) : t.splits.length > 0 ? (
                  // Each part has its own category; edit them in the details panel.
                  <button
                    type="button"
                    onClick={() => setOpenId(t.id)}
                    className="flex items-center gap-2 px-2.5 text-sm hover:underline"
                    title={t.splits
                      .map((s) => `${formatCurrency(s.amount_cents)} ${categoryLabel(s.counted_category)}`)
                      .join("\n")}
                  >
                    <span className="flex gap-0.5">
                      {t.splits.map((s) => (
                        <span
                          key={s.id}
                          className="size-2 shrink-0 rounded-[2px]"
                          style={{ background: categoryColor(s.counted_category) }}
                        />
                      ))}
                    </span>
                    Split · {t.splits.length} parts
                  </button>
                ) : t.reimburses_id !== null ? (
                  // A payback counts as its purchase's category; change it on the purchase.
                  <button
                    type="button"
                    onClick={() => setOpenId(t.reimburses_id)}
                    className="flex items-center gap-2 px-2.5 text-sm hover:underline"
                    title="Pays back a purchase, so it counts in that purchase's category. Click to open the purchase."
                  >
                    <span
                      className="size-2 shrink-0 rounded-[2px]"
                      style={{ background: categoryColor(t.counted_category) }}
                    />
                    {categoryLabel(t.counted_category)}
                    <Badge variant="secondary" className="h-4 px-1 text-[10px]">
                      pays back
                    </Badge>
                  </button>
                ) : (
                  <Select
                    items={{ ...CATEGORY_ITEMS, [t.category]: categoryLabel(t.category) }}
                    value={t.category}
                    onValueChange={(category) =>
                      category && category !== t.category && save(t, { category })
                    }
                    disabled={saving === t.id}
                  >
                    <SelectTrigger size="sm" className="w-40" aria-label={`Category for ${t.description}`}>
                      <span
                        className="size-2 shrink-0 rounded-[2px]"
                        style={{ background: categoryColor(t.category) }}
                      />
                      <SelectValue />
                      {t.category_source === "manual" && (
                        <Badge variant="secondary" className="ml-auto h-4 px-1 text-[10px]" title="Set by you; rules won't change it">
                          you
                        </Badge>
                      )}
                    </SelectTrigger>
                    <SelectContent>
                      {Object.entries(CATEGORY_ITEMS).map(([value, label]) => (
                        <SelectItem key={value} value={value}>
                          {label}
                        </SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                )}
              </TableCell>
              <TableCell
                // Less padding, so an amount with a note under it still fits the row height.
                className={cn("py-1 text-right tabular", t.amount_cents > 0 && "text-positive")}
              >
                {formatCurrency(t.amount_cents)}
                {t.pending && (
                  <span
                    className="block text-xs text-muted-foreground"
                    title="Your bank hasn't finalized this yet; the amount can still change"
                  >
                    pending
                  </span>
                )}
                {t.reimbursement_status === "waiting" ? (
                  <span className="block text-xs text-muted-foreground" title="Not counted as spending">
                    {t.reimbursed_cents > 0
                      ? `${formatCurrency(-t.amount_cents - t.reimbursed_cents)} still owed`
                      : "owed to you"}
                  </span>
                ) : t.reimbursement_status === "received" ? (
                  <span className="block text-xs text-positive" title="Not counted as spending">
                    paid back
                  </span>
                ) : (
                  t.reimbursed_cents > 0 && (
                    <span className="block text-xs text-positive">
                      {formatCurrency(t.reimbursed_cents)} back
                    </span>
                  )
                )}
              </TableCell>
              <TableCell className="text-center">
                <Switch
                  size="sm"
                  checked={t.is_transfer}
                  // A linked payback, paid-back purchase or reimbursable purchase can't be a
                  // transfer; unlink or unmark it first.
                  disabled={
                    saving === t.id ||
                    t.reimburses_id !== null ||
                    t.reimbursement_ids.length > 0 ||
                    t.reimbursable ||
                    t.splits.length > 0
                  }
                  onCheckedChange={(is_transfer) => save(t, { is_transfer })}
                  aria-label={`${t.description} is a transfer between my accounts`}
                />
              </TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>
      <TransactionDetails
        transactionId={openId}
        onClose={() => setOpenId(null)}
        onSelect={setOpenId}
        onChanged={() => {
          reload();
          onEdited?.();
        }}
      />
      {paged && pages > 1 && (
        <div className="flex flex-wrap items-center justify-between gap-2 text-sm text-muted-foreground">
          <span>{data.total} transactions</span>
          <div className="flex items-center gap-2">
            <Button variant="outline" size="sm" disabled={page === 0} onClick={() => setPage(page - 1)}>
              Previous
            </Button>
            {/* Keyed on the page so the box shows the new number after Previous/Next. */}
            <PageJump key={page} page={page} pages={pages} onJump={setPage} />
            <Button
              variant="outline"
              size="sm"
              disabled={page + 1 >= pages}
              onClick={() => setPage(page + 1)}
            >
              Next
            </Button>
          </div>
        </div>
      )}
    </div>
  );
}

/** "Page [3] of 16": type a page number and press Enter (or click away) to go there. */
function PageJump({
  page,
  pages,
  onJump,
}: {
  page: number;
  pages: number;
  onJump: (page: number) => void;
}) {
  const [text, setText] = useState(String(page + 1));

  function go() {
    const target = pageIndex(text, pages);
    if (target === null) setText(String(page + 1)); // not a number: put the current page back
    else if (target !== page) onJump(target);
    else setText(String(page + 1)); // e.g. "99" on the last page: show what it clamped to
  }

  return (
    <form
      className="flex items-center gap-1.5"
      onSubmit={(e) => {
        e.preventDefault();
        go();
      }}
    >
      <span>Page</span>
      <Input
        value={text}
        onChange={(e) => setText(e.target.value)}
        onBlur={go}
        onFocus={(e) => e.target.select()}
        inputMode="numeric"
        aria-label={`Page number, 1 to ${pages}`}
        className="h-7 w-12 px-1 text-center tabular"
      />
      <span>of {pages}</span>
    </form>
  );
}
