import { describe, expect, it } from "vitest";

import { checkOpening, goalStatus, parseOptionalDollars } from "./budget";

describe("parseOptionalDollars", () => {
  it("treats an empty box as $0", () => {
    expect(parseOptionalDollars("  ")).toBe(0);
    expect(parseOptionalDollars("12.5")).toBe(1250);
    expect(parseOptionalDollars("abc")).toBeNull();
  });
});

describe("checkOpening", () => {
  it("counts what's left", () => {
    expect(checkOpening(100_000, ["500", "", "250.50"])).toEqual({
      leftCents: 24_950,
      problem: null,
    });
  });
  it("can't go over what you have", () => {
    expect(checkOpening(10_000, ["150"]).problem).toBe("That's $50.00 more than you have");
  });
  it("flags amounts it can't read", () => {
    expect(checkOpening(10_000, ["1.234"]).problem).toMatch(/should look like/);
  });
});

describe("goalStatus", () => {
  const today = new Date(2026, 10, 14);
  it("shows what's left and the deadline", () => {
    expect(goalStatus(18_000, 50_000, "2026-12-20", today)).toBe(
      "$320.00 to go · by Dec 20 (36 days)",
    );
    expect(goalStatus(18_000, 50_000, null, today)).toBe("$320.00 to go");
    expect(goalStatus(18_000, 50_000, "2026-11-01", today)).toBe("$320.00 to go · past its date");
  });
  it("celebrates a reached goal", () => {
    expect(goalStatus(50_000, 50_000, "2026-12-20", today)).toBe("Reached!");
  });
});
