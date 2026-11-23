"use client";

import { useEffect, useState } from "react";

import { cn } from "@/lib/utils";

/**
 * The colored part of a progress bar. It grows from empty when it first appears, and slides
 * to a new width when the number changes. Put it inside the bar's gray track.
 */
export function FillBar({
  percent,
  className,
  color,
}: {
  percent: number;
  className?: string;
  color?: string;
}) {
  const [width, setWidth] = useState(0);
  // Start at 0, then set the real width on the next frame, so the browser animates it.
  useEffect(() => {
    const frame = requestAnimationFrame(() => setWidth(percent));
    return () => cancelAnimationFrame(frame);
  }, [percent]);
  return (
    <div
      className={cn("h-full rounded-full transition-[width] duration-700 ease-out", className)}
      style={{ width: `${Math.min(Math.max(width, 0), 100)}%`, background: color }}
    />
  );
}
