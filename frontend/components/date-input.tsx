"use client";

import { useEffect, useRef, useState } from "react";

import { Input } from "@/components/ui/input";

/** How long to wait after the last keystroke before searching. */
const TYPING_PAUSE_MS = 800;

type DateInputProps = Omit<React.ComponentProps<typeof Input>, "type" | "value" | "onChange"> & {
  /** "YYYY-MM-DD", or "" for no date. */
  value: string;
  /** Called with "YYYY-MM-DD", or "" when the box is cleared. */
  onCommit: (value: string) => void;
};

/**
 * A date box that waits for you to finish typing before it searches.
 *
 * A plain <input type="date"> reports a change as soon as the date is complete, and typing
 * "3" in the day already makes a complete date (the 3rd). Searching right away redraws the
 * box, which throws away the "3", so the "0" for the 30th starts over. This box keeps what
 * you type to itself and only passes it on after a short pause, on Enter, or when you click
 * away. Picking a day from the calendar pop-up works the same way, after the short pause.
 */
export function DateInput({ value, onCommit, onBlur, onKeyDown, ...props }: DateInputProps) {
  const [draft, setDraft] = useState(value);
  const timer = useRef<ReturnType<typeof setTimeout>>(undefined);

  // When the date changes from outside (a preset button, "Clear filters"), show it.
  const [lastValue, setLastValue] = useState(value);
  if (value !== lastValue) {
    setLastValue(value);
    setDraft(value);
  }

  useEffect(() => () => clearTimeout(timer.current), []);

  const commit = (next: string) => {
    clearTimeout(timer.current);
    if (next !== value) onCommit(next);
  };

  return (
    <Input
      {...props}
      type="date"
      value={draft}
      onChange={(e) => {
        const next = e.target.value;
        setDraft(next);
        clearTimeout(timer.current);
        timer.current = setTimeout(() => commit(next), TYPING_PAUSE_MS);
      }}
      onBlur={(e) => {
        commit(draft);
        onBlur?.(e);
      }}
      onKeyDown={(e) => {
        if (e.key === "Enter") commit(draft);
        onKeyDown?.(e);
      }}
    />
  );
}
