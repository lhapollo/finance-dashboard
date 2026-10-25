"use client";

import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { Suspense, useState } from "react";

import { TransactionsTable, type TransactionFilters } from "@/components/transactions-table";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { query } from "@/lib/api";
import { categoryLabel } from "@/lib/categories";
import { formatDay } from "@/lib/format";

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

/** Filters live in the URL, so a link like /transactions?category=dining opens filtered. */
function FilteredTransactions() {
  const params = useSearchParams();
  const router = useRouter();
  const pathname = usePathname();

  const filters: TransactionFilters = {
    category: params.get("category") ?? undefined,
    start: params.get("start") ?? undefined,
    end: params.get("end") ?? undefined,
    search: params.get("search") ?? undefined,
  };
  const [search, setSearch] = useState(filters.search ?? "");

  const setFilters = (next: TransactionFilters) =>
    router.replace(`${pathname}${query(next)}`, { scroll: false });

  const active = [
    filters.category && `Category: ${categoryLabel(filters.category)}`,
    filters.start && `From ${formatDay(filters.start)}`,
    filters.end && `Before ${formatDay(filters.end)}`, // end itself isn't included
  ].filter(Boolean);

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
          {active.map((label) => (
            <span key={label as string} className="rounded-md bg-muted px-2 py-1 text-xs">
              {label}
            </span>
          ))}
          {(active.length > 0 || filters.search) && (
            <Button
              type="button"
              variant="ghost"
              size="sm"
              onClick={() => {
                setSearch("");
                setFilters({});
              }}
            >
              Clear filters
            </Button>
          )}
        </form>
        <TransactionsTable filters={filters} />
      </CardContent>
    </Card>
  );
}
