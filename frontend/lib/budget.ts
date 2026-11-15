import { formatCurrency, formatDay, parseDate } from "./format";
import { parseDollars } from "./splits";

/** Typed dollars, where an empty box means $0. Null when it isn't an amount. */
export function parseOptionalDollars(text: string): number | null {
  return text.trim() === "" ? 0 : parseDollars(text);
}

/**
 * The fresh-start split: how much of `availableCents` the typed amounts leave unassigned,
 * and what's stopping it from being saved (null when it can be).
 */
export function checkOpening(
  availableCents: number,
  typed: string[],
): { leftCents: number; problem: string | null } {
  const amounts = typed.map(parseOptionalDollars);
  const leftCents = availableCents - amounts.reduce<number>((sum, c) => sum + (c ?? 0), 0);
  let problem: string | null = null;
  if (amounts.some((c) => c === null)) problem = "Each amount should look like 45 or 45.50";
  else if (leftCents < 0) problem = `That's ${formatCurrency(-leftCents)} more than you have`;
  return { leftCents, problem };
}

/** "$320.00 to go · by Dec 20 (36 days)", or "Reached!" once the goal is met. */
export function goalStatus(
  balanceCents: number,
  targetCents: number,
  targetDate: string | null,
  today = new Date(),
): string {
  const toGo = targetCents - balanceCents;
  if (toGo <= 0) return "Reached!";
  let text = `${formatCurrency(toGo)} to go`;
  if (targetDate) {
    const start = new Date(today.getFullYear(), today.getMonth(), today.getDate());
    const days = Math.round((parseDate(targetDate).getTime() - start.getTime()) / 86_400_000);
    text += days >= 0 ? ` · by ${formatDay(targetDate, today)} (${days} days)` : " · past its date";
  }
  return text;
}
