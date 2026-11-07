import { describe, expect, it } from "vitest";

import { checkSplit, parseDollars } from "./splits";

describe("parseDollars", () => {
  it.each([
    ["45", 4500],
    ["45.5", 4550],
    ["45.50", 4550],
    ["0.07", 7],
    ["1,300", 130000],
    ["$12.34", 1234],
    [" 9 ", 900],
  ])("reads %j as %i cents", (text, cents) => {
    expect(parseDollars(text)).toBe(cents);
  });

  it.each(["", "abc", "-5", "1.234", "0", "0.00", "1.2.3", "$"])("rejects %j", (text) => {
    expect(parseDollars(text)).toBeNull();
  });
});

describe("checkSplit", () => {
  it("is ready when the parts add up, whatever the transaction's sign", () => {
    expect(checkSplit(134500, ["1300", "45"])).toEqual({ leftCents: 0, problem: null });
    expect(checkSplit(-12000, ["90", "30.00"])).toEqual({ leftCents: 0, problem: null });
  });

  it("says how much is left or too much", () => {
    expect(checkSplit(134500, ["1300", ""]).problem).toBe("Each part needs an amount, like 45.00");
    expect(checkSplit(134500, ["1300", "40"])).toEqual({
      leftCents: 500,
      problem: "$5.00 left to assign",
    });
    expect(checkSplit(134500, ["1300", "50"]).problem).toBe("$5.00 too much");
  });

  it("needs at least two parts", () => {
    expect(checkSplit(4500, ["45"]).problem).toBe("Add at least 2 parts");
  });
});
