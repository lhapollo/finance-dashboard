import { describe, expect, it } from "vitest";

import { formatCurrency } from "./format";

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
