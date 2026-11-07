"use client";

import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { Suspense, useState } from "react";

import { DateInput } from "@/components/date-input";
import {
  TransactionsTable,
  type SortOrder,
  type TransactionFilters,
} from "@/components/transactions-table";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Switch } from "@/components/ui/switch";
import { query } from "@/lib/api";
import { ALL_CATEGORIES, categoryColor, categoryLabel } from "@/lib/categories";
import { addDays, datePresets, type DateRange } from "@/lib/format";
import { cn } from "@/lib/utils";

// The Select needs a value for "no filter"; it never reaches the URL or the API.
const ALL = "all";
const CATEGORY_ITEMS = {
  [ALL]: "All categories",
  ...Object.fromEntries(ALL_CATEGORIES.map((c) => [c, categoryLabel(c)])),
};
const MONEY_ITEMS = { [ALL]: "Money in and out", out: "Money out", in: "Money in" };

export default function TransactionsPage() {
  return (
    <>
      <h1 className="text-xl font-semibold">Transactions</h1>
      {/* Reading the URL's ?filters needs a Suspense boundary in Next.js. */}
      <Suspense>
        <FilteredTransactions />
      </Suspense>
    </>
  );
}

/** Filters live in the URL, so a link like /transactions?category=dining opens filtered,
 * and a refresh or a bookmark keeps them. */
function FilteredTransactions() {
  const params = useSearchParams();
  const router = useRouter();
  const pathname = usePathname();

  const money = params.get("money");
  const filters: TransactionFilters = {
    category: params.get("category") ?? undefined,
    money: money === "in" || money === "out" ? money : undefined,
    is_transfer: params.get("is_transfer") === "false" ? false : undefined,
    reimbursable: params.get("reimbursable") === "true" ? true : undefined,
    start: params.get("start") ?? undefined,
    end: params.get("end") ?? undefined,
    search: params.get("search") ?? undefined,
    order: params.get("order") === "asc" ? "asc" : undefined, // newest first is the default
  };
  const [search, setSearch] = useState(filters.search ?? "");

  const setFilters = (next: TransactionFilters) =>
    router.replace(`${pathname}${query(next)}`, { scroll: false });
  const setRange = (range: DateRange) => setFilters({ ...filters, ...range });

  // The API's end date is excluded; the "To" box shows the last day that's included.
  const toInclusive = filters.end ? addDays(filters.end, -1) : "";
  const presets = datePresets();
  const activePreset = presets.find(
    (p) => p.range.start === filters.start && p.range.end === filters.end,
  )?.label;

  const anyFilter =
    filters.category ||
    filters.money ||
    filters.is_transfer === false ||
    filters.reimbursable ||
    filters.start ||
    filters.end ||
    filters.search;

  return (
    <Card>
      <CardContent className="flex flex-col gap-4">
        <form
          className="flex flex-wrap items-center gap-2"
          onSubmit={(e) => {
            e.preventDefault();
            setFilters({ ...filters, search: search.trim() || undefined });
          }}
        >
          <Input
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder="Search descriptions…"
            className="w-64"
            aria-label="Search descriptions"
          />
          <Button type="submit" variant="outline" size="sm">
            Search
          </Button>
          <Select
            // A category from an old link that isn't in the list still gets a label.
            items={
              filters.category
                ? { ...CATEGORY_ITEMS, [filters.category]: categoryLabel(filters.category) }
                : CATEGORY_ITEMS
            }
            value={filters.category ?? ALL}
            onValueChange={(value) =>
              setFilters({ ...filters, category: !value || value === ALL ? undefined : value })
            }
          >
            <SelectTrigger size="sm" className="w-44" aria-label="Category">
              {filters.category && (
                <span
                  className="size-2 shrink-0 rounded-[2px]"
                  style={{ background: categoryColor(filters.category) }}
                />
              )}
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
          <Select
            items={MONEY_ITEMS}
            value={filters.money ?? ALL}
            onValueChange={(value) =>
              setFilters({
                ...filters,
                money: value === "in" || value === "out" ? value : undefined,
              })
            }
          >
            <SelectTrigger size="sm" className="w-40" aria-label="Money in or out">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              {Object.entries(MONEY_ITEMS).map(([value, label]) => (
                <SelectItem key={value} value={value}>
                  {label}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
          <label className="flex items-center gap-2 text-sm text-muted-foreground">
            <Switch
              size="sm"
              checked={filters.is_transfer === false}
              onCheckedChange={(hide) =>
                setFilters({ ...filters, is_transfer: hide ? false : undefined })
              }
            />
            Hide transfers
          </label>
          {filters.reimbursable && (
            <Button
              type="button"
              variant="secondary"
              size="sm"
              onClick={() => setFilters({ ...filters, reimbursable: undefined })}
              aria-label="Stop showing only reimbursable purchases"
            >
              Reimbursable only ×
            </Button>
          )}
          {anyFilter && (
            <Button
              type="button"
              variant="ghost"
              size="sm"
              onClick={() => {
                setSearch("");
                setFilters({ order: filters.order });
              }}
            >
              Clear filters
            </Button>
          )}
        </form>

        <div className="flex flex-wrap items-center gap-x-4 gap-y-2 text-sm">
          <div className="flex items-center gap-2">
            <label className="flex items-center gap-1.5 text-muted-foreground">
              From
              <DateInput
                value={filters.start ?? ""}
                max={toInclusive || undefined}
                onCommit={(start) => setRange({ start: start || undefined, end: filters.end })}
                className="h-8 w-40"
              />
            </label>
            <label className="flex items-center gap-1.5 text-muted-foreground">
              To
              <DateInput
                value={toInclusive}
                min={filters.start}
                onCommit={(to) =>
                  setRange({ start: filters.start, end: to ? addDays(to, 1) : undefined })
                }
                className="h-8 w-40"
              />
            </label>
          </div>
          <div className="flex flex-wrap gap-1" role="group" aria-label="Date presets">
            {presets.map(({ label, range }) => (
              <Button
                key={label}
                type="button"
                size="xs"
                variant={activePreset === label ? "secondary" : "ghost"}
                aria-pressed={activePreset === label}
                className={cn(activePreset === label && "font-medium")}
                onClick={() => setRange(range)}
              >
                {label}
              </Button>
            ))}
          </div>
        </div>

        <TransactionsTable
          filters={filters}
          onOrderChange={(order: SortOrder) =>
            setFilters({ ...filters, order: order === "asc" ? "asc" : undefined })
          }
        />
      </CardContent>
    </Card>
  );
}
