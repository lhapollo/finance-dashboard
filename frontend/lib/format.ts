const cad = new Intl.NumberFormat("en-CA", { style: "currency", currency: "CAD" });

/**
 * Formats an amount as Canadian dollars, e.g. -4.5 -> "-$4.50".
 * Accepts strings because the API sends money as strings like "-4.50"
 * (the backend keeps it as Decimal, and JSON numbers would lose precision).
 */
export function formatCurrency(amount: number | string): string {
  return cad.format(Number(amount));
}
