import { describe, expect, it } from "vitest";

import {
  addDays,
  addMonths,
  datePresets,
  toIsoDate,
  currentMonth,
  daysSince,
  formatCompactCurrency,
  formatCurrency,
  formatDay,
  formatMonth,
  formatWholeDollars,
  monthStarts,
} from "./format";

describe("formatCurrency", () => {
  it("formats a purchase (negative) with a minus sign and two decimals", () => {
    expect(formatCurrency(-450)).toBe("-$4.50");
  });

  it("formats a payment (positive) with a thousands separator", () => {
    expect(formatCurrency(123456)).toBe("$1,234.56");
  });

  it("formats amounts under a dollar", () => {
    expect(formatCurrency(-5)).toBe("-$0.05");
  });

  it("formats zero", () => {
    expect(formatCurrency(0)).toBe("$0.00");
  });
});

describe("short money formats", () => {
  it("drops cents for headline numbers", () => {
    expect(formatWholeDollars(140216)).toBe("$1,402");
  });

  it("compacts axis labels", () => {
    expect(formatCompactCurrency(150000)).toBe("$1.5K");
    expect(formatCompactCurrency(0)).toBe("$0");
  });
});

describe("dates", () => {
  it("doesn't shift the day by timezone", () => {
    // new Date("2026-10-01") is UTC midnight, which is Sept 30 in Toronto.
    expect(formatMonth("2026-10-01")).toBe("Oct 2026");
    expect(formatDay("2026-10-01", new Date(2026, 5, 1))).toBe("Oct 1");
  });

  it("adds the year to days outside the current year", () => {
    expect(formatDay("2024-10-01", new Date(2026, 5, 1))).toBe("Oct 1, 2024");
  });

  it("adds and subtracts months across year boundaries", () => {
    expect(addMonths("2026-01", -1)).toBe("2025-12");
    expect(addMonths("2026-12", 1)).toBe("2027-01");
    expect(addMonths("2026-10", -12)).toBe("2025-10");
  });

  it("lists the month starts ending with a month", () => {
    expect(monthStarts("2026-01", 3)).toEqual(["2025-11-01", "2025-12-01", "2026-01-01"]);
  });

  it("formats the current month as YYYY-MM", () => {
    expect(currentMonth(new Date(2026, 0, 31))).toBe("2026-01");
  });
});

describe("date ranges", () => {
  it("adds days across month and year ends", () => {
    expect(addDays("2026-10-31", 1)).toBe("2026-11-01");
    expect(addDays("2026-12-31", 1)).toBe("2027-01-01");
    expect(addDays("2026-03-01", -1)).toBe("2026-02-28");
  });

  it("formats dates in local time", () => {
    expect(toIsoDate(new Date(2026, 0, 5))).toBe("2026-01-05");
  });

  it("builds presets relative to today, with end excluded", () => {
    const presets = Object.fromEntries(
      datePresets(new Date(2026, 0, 15)).map((p) => [p.label, p.range]),
    );
    expect(presets["This month"]).toEqual({ start: "2026-01-01", end: "2026-02-01" });
    expect(presets["Last month"]).toEqual({ start: "2025-12-01", end: "2026-01-01" });
    expect(presets["Last 3 months"]).toEqual({ start: "2025-11-01", end: "2026-02-01" });
    expect(presets["This year"]).toEqual({ start: "2026-01-01", end: "2027-01-01" });
    expect(presets["All time"]).toEqual({});
  });
});

describe("daysSince", () => {
  const today = new Date(2026, 10, 7, 15, 30); // Nov 7, mid-afternoon

  it("counts whole days, ignoring the time of day", () => {
    expect(daysSince("2026-11-07", today)).toBe(0);
    expect(daysSince("2026-11-06", today)).toBe(1);
    expect(daysSince("2026-10-28", today)).toBe(10);
  });

  it("works across a daylight saving change", () => {
    expect(daysSince("2026-10-31", today)).toBe(7); // clocks went back Nov 1
  });
});
