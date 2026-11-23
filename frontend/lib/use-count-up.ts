import { useEffect, useRef, useState } from "react";

/** True when the person asked their computer for less motion (macOS: Reduce motion). */
export function prefersReducedMotion(): boolean {
  return typeof window !== "undefined" && window.matchMedia("(prefers-reduced-motion: reduce)").matches;
}

/** Fast at first, gentle at the end. */
const easeOut = (t: number) => 1 - (1 - t) ** 3;

/**
 * A number that glides to `target` instead of jumping: from 0 the first time, then from
 * wherever it was whenever `target` changes. Shows `target` straight away with reduced motion.
 */
export function useCountUp(target: number, durationMs = 600): number {
  const [shown, setShown] = useState(() => (prefersReducedMotion() ? target : 0));
  const current = useRef(shown); // what's on screen right now, even mid-animation

  useEffect(() => {
    const from = current.current;
    if (from === target) return;
    if (prefersReducedMotion()) {
      current.current = target;
      setShown(target);
      return;
    }
    const start = performance.now();
    let frame = requestAnimationFrame(function step(now) {
      const t = Math.min((now - start) / durationMs, 1);
      current.current = Math.round(from + (target - from) * easeOut(t));
      setShown(current.current);
      if (t < 1) frame = requestAnimationFrame(step);
    });
    return () => cancelAnimationFrame(frame);
  }, [target, durationMs]);

  return shown;
}
