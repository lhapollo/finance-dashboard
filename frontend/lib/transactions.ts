export type ForeignAmount = { amount: string; currency: string; rate: string };

/**
 * Card descriptions for purchases in another currency end with the original amount and
 * the exchange rate: "MTA*NYCT PAYGO NEW YORK, NY 3.00 USD @ 1.393333". Pulls those out
 * for display; the amount in our data is always the converted CAD one.
 */
export function foreignAmount(rawDescription: string): ForeignAmount | null {
  const match = rawDescription.match(/(\d*\.\d{2}) ([A-Z]{3}) @ ([\d.]+)$/);
  if (!match) return null;
  const [, amount, currency, rate] = match;
  return { amount: amount.startsWith(".") ? `0${amount}` : amount, currency, rate };
}

/**
 * What someone typed in the "Page [ ] of N" box, as a 0-based page index. Out-of-range
 * numbers go to the nearest real page (99 of 16 -> the last page); non-numbers give null.
 */
export function pageIndex(typed: string, pages: number): number | null {
  const n = Number.parseInt(typed.trim(), 10);
  if (Number.isNaN(n)) return null;
  return Math.min(Math.max(n, 1), pages) - 1;
}
