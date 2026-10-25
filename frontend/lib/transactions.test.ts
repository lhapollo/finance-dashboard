import { describe, expect, it } from "vitest";

import { foreignAmount, pageIndex } from "./transactions";

describe("foreignAmount", () => {
  it("reads the original amount and rate", () => {
    expect(foreignAmount("MTA*NYCT PAYGO NEW YORK, NY 3.00 USD @ 1.393333")).toEqual({
      amount: "3.00",
      currency: "USD",
      rate: "1.393333",
    });
  });

  it("adds a leading zero to amounts under a dollar", () => {
    expect(foreignAmount("Files-Edit.com Sheridan, WY .80 USD @ 1.425000")?.amount).toBe("0.80");
  });

  it("returns null for Canadian purchases", () => {
    expect(foreignAmount("LOBLAWS #1042 TORONTO, ON")).toBeNull();
  });
});

describe("pageIndex", () => {
  it("turns a typed page number into a 0-based index", () => {
    expect(pageIndex("3", 16)).toBe(2);
    expect(pageIndex(" 1 ", 16)).toBe(0);
  });

  it("clamps out-of-range numbers to the nearest page", () => {
    expect(pageIndex("99", 16)).toBe(15);
    expect(pageIndex("0", 16)).toBe(0);
    expect(pageIndex("-4", 16)).toBe(0);
  });

  it("ignores text that isn't a number", () => {
    expect(pageIndex("", 16)).toBeNull();
    expect(pageIndex("abc", 16)).toBeNull();
  });
});
