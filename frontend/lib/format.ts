const cad = new Intl.NumberFormat("en-CA", { style: "currency", currency: "CAD" });

/**
 * Formats whole cents as Canadian dollars, e.g. -450 -> "-$4.50".
 * The API sends money as integer cents; this is the only place they become dollars.
 */
export function formatCurrency(cents: number): string {
  return cad.format(cents / 100);
}
