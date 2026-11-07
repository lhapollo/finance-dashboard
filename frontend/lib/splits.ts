import { formatCurrency } from "./format";

/**
 * Typed dollars to whole cents: "45" -> 4500, "1,300.5" -> 130050, "$12.34" -> 1234.
 * Null for anything that isn't a positive amount with at most two decimals. (Split parts
 * are typed without a sign; they take the sign of the transaction.)
 */
export function parseDollars(text: string): number | null {
  const cleaned = text.trim().replace(/^\$/, "").replaceAll(",", "");
  const match = /^(\d+)(?:\.(\d{1,2}))?$/.exec(cleaned);
  if (!match) return null;
  const cents = Number(match[1]) * 100 + Number((match[2] ?? "").padEnd(2, "0"));
  return cents > 0 ? cents : null;
}

/**
 * What still has to be assigned before parts (typed dollars) add up to a transaction
 * of `totalCents`, and what's wrong if they can't be saved yet (null when they can).
 */
export function checkSplit(
  totalCents: number,
  typed: string[],
): { leftCents: number; problem: string | null } {
  const total = Math.abs(totalCents);
  const parts = typed.map(parseDollars);
  const leftCents = total - parts.reduce<number>((sum, c) => sum + (c ?? 0), 0);

  let problem: string | null = null;
  if (typed.length < 2) problem = "Add at least 2 parts";
  else if (parts.some((c) => c === null)) problem = "Each part needs an amount, like 45.00";
  else if (leftCents > 0) problem = `${formatCurrency(leftCents)} left to assign`;
  else if (leftCents < 0) problem = `${formatCurrency(-leftCents)} too much`;
  return { leftCents, problem };
}
