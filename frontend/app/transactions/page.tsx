"use client";

import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { Suspense, useState } from "react";

import {
  TransactionsTable,
  type SortOrder,
  type TransactionFilters,
} from "@/components/transactions-table";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { query } from "@/lib/api";
import { categoryLabel } from "@/lib/categories";
import { addDays, datePresets, type DateRange } from "@/lib/format";
import { cn } from "@/lib/utils";

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

  const filters: TransactionFilters = {
    category: params.get("category") ?? undefined,
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

  const anyFilter = filters.category || filters.start || filters.end || filters.search;

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
          {filters.category && (
            <span className="rounded-md bg-muted px-2 py-1 text-xs">
              Category: {categoryLabel(filters.category)}
            </span>
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
              <Input
                type="date"
                value={filters.start ?? ""}
                max={toInclusive || undefined}
                onChange={(e) => setRange({ start: e.target.value || undefined, end: filters.end })}
                className="h-8 w-40"
              />
            </label>
            <label className="flex items-center gap-1.5 text-muted-foreground">
              To
              <Input
                type="date"
                value={toInclusive}
                min={filters.start}
                onChange={(e) =>
                  setRange({
                    start: filters.start,
                    end: e.target.value ? addDays(e.target.value, 1) : undefined,
                  })
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
