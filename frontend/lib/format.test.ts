import { describe, expect, it } from "vitest";

import { formatCurrency } from "./format";

describe("formatCurrency", () => {
  it("formats a purchase (negative) with a minus sign and two decimals", () => {
    expect(formatCurrency(-4.5)).toBe("-$4.50");
  });

  it("formats a payment (positive)", () => {
    expect(formatCurrency(1234.56)).toBe("$1,234.56");
  });

  it("accepts amounts sent by the API as strings", () => {
    expect(formatCurrency("-4.50")).toBe("-$4.50");
  });

  it("formats zero", () => {
    expect(formatCurrency(0)).toBe("$0.00");
  });
});
