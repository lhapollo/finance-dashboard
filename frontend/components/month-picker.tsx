"use client";

import { ChevronLeftIcon, ChevronRightIcon } from "lucide-react";

import { Button } from "@/components/ui/button";
import { addMonths, currentMonth, formatMonth } from "@/lib/format";

/** "< Oct 2026 >". `month` is "YYYY-MM"; you can't go past the current month. */
export function MonthPicker({
  month,
  onChange,
}: {
  month: string;
  onChange: (month: string) => void;
}) {
  const atLatest = month >= currentMonth();
  return (
    <div className="flex items-center gap-1">
      <Button
        variant="outline"
        size="icon-sm"
        aria-label="Previous month"
        onClick={() => onChange(addMonths(month, -1))}
      >
        <ChevronLeftIcon />
      </Button>
      <span className="w-24 text-center text-sm font-medium">{formatMonth(`${month}-01`)}</span>
      <Button
        variant="outline"
        size="icon-sm"
        aria-label="Next month"
        disabled={atLatest}
        onClick={() => onChange(addMonths(month, 1))}
      >
        <ChevronRightIcon />
      </Button>
    </div>
  );
}
