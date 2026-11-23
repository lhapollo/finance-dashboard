"use client";

import { useCountUp } from "@/lib/use-count-up";

/** An amount that counts to its new value, e.g. <AnimatedNumber value={cents} format={formatCurrency} />. */
export function AnimatedNumber({ value, format }: { value: number; format: (n: number) => string }) {
  const shown = useCountUp(value);
  return (
    // Screen readers get the final amount once, not every in-between frame.
    <span aria-label={format(value)}>
      <span aria-hidden>{format(shown)}</span>
    </span>
  );
}
