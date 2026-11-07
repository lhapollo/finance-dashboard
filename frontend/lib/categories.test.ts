import { describe, expect, it } from "vitest";

import { categoryColor, categoryLabel, OTHER, seriesFor, toChartRows } from "./categories";

describe("seriesFor / categoryColor", () => {
  it("gives the big categories their own fixed slot", () => {
    expect(seriesFor("dining")).toBe("dining");
    expect(categoryColor("dining")).toBe("var(--cat-1)");
    expect(categoryColor("subscriptions")).toBe("var(--cat-7)");
  });

  it("folds everything else into Other", () => {
    expect(seriesFor("travel")).toBe(OTHER);
    expect(seriesFor("uncategorized")).toBe(OTHER);
    expect(categoryColor("travel")).toBe("var(--cat-other)");
  });
});

describe("categoryLabel", () => {
  it("capitalizes", () => {
    expect(categoryLabel("uncategorized")).toBe("Uncategorized");
  });
});

describe("toChartRows", () => {
  const periods = ["2026-09-01", "2026-10-01"];

  it("draws a series that refunds pushed below zero as 0", () => {
    const rows = toChartRows(
      [
        { period: "2026-10-01", category: "dining", total_cents: -260 },
        { period: "2026-10-01", category: "travel", total_cents: 900 },
        { period: "2026-10-01", category: "health", total_cents: -300 }, // nets with travel in Other
      ],
      periods,
    );

    expect(rows[1].dining).toBe(0);
    expect(rows[1][OTHER]).toBe(600);
  });

  it("makes one row per period with a column per series", () => {
    const rows = toChartRows([{ period: "2026-10-01", category: "dining", total_cents: 500 }], periods);

    expect(rows).toHaveLength(2);
    expect(rows[1].dining).toBe(500);
    expect(rows[1].shopping).toBe(0);
  });

  it("fills months with no spending with zeros, so the axis has no gaps", () => {
    const rows = toChartRows([], periods);

    expect(rows.map((r) => r.period)).toEqual(periods);
    expect(rows[0].dining).toBe(0);
  });

  it("adds up the small categories into Other", () => {
    const rows = toChartRows(
      [
        { period: "2026-10-01", category: "travel", total_cents: 300 },
        { period: "2026-10-01", category: "fees", total_cents: 200 },
      ],
      periods,
    );

    expect(rows[1][OTHER]).toBe(500);
  });

  it("ignores periods outside the requested range", () => {
    const rows = toChartRows([{ period: "2025-01-01", category: "dining", total_cents: 1 }], periods);

    expect(rows.every((r) => r.dining === 0)).toBe(true);
  });
});
