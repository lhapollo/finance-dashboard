"use client";

import { Input } from "@/components/ui/input";

/** A dollar amount box: "$" in front, right-aligned digits. The value is the typed text;
 * parse it with parseDollars. */
export function MoneyInput({
  value,
  onChange,
  ...props
}: Omit<React.ComponentProps<typeof Input>, "value" | "onChange"> & {
  value: string;
  onChange: (value: string) => void;
}) {
  return (
    <div className="relative w-32">
      <span className="pointer-events-none absolute top-1/2 left-2.5 -translate-y-1/2 text-muted-foreground">
        $
      </span>
      <Input
        {...props}
        inputMode="decimal"
        value={value}
        onChange={(e) => onChange(e.target.value)}
        className="pl-6 text-right tabular"
        placeholder={props.placeholder ?? "0.00"}
      />
    </div>
  );
}
