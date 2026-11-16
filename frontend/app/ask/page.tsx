"use client";

import { useEffect, useRef, useState } from "react";

import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { api, type AskResponse, type AskStep } from "@/lib/api";
import { cn } from "@/lib/utils";

const SUGGESTIONS = [
  "How much did I spend on food last month vs the month before?",
  "Where did I spend the most money last month?",
  "Can I afford a $60 game from my Fun bucket?",
  "How much more do I need for the Switch 2?",
  "Which buckets are overspent?",
];

/** What each tool does, in words, for "How I got this". */
const TOOL_NAMES: Record<string, string> = {
  get_spending: "Added up spending",
  compare_spending: "Compared two periods",
  get_income: "Added up income",
  top_merchants: "Ranked merchants",
  find_transactions: "Looked up transactions",
  get_budget: "Checked the budget",
  can_i_afford: "Checked what fits",
  get_balances: "Checked balances",
};

type Turn = {
  question: string;
  answer?: string;
  steps?: AskStep[];
  error?: string;
};

export default function AskPage() {
  const [turns, setTurns] = useState<Turn[]>([]);
  const [question, setQuestion] = useState("");
  const [busy, setBusy] = useState(false);
  const bottom = useRef<HTMLDivElement>(null);

  useEffect(() => {
    bottom.current?.scrollIntoView({ behavior: "smooth", block: "end" });
  }, [turns]);

  async function send(text: string) {
    const q = text.trim();
    if (!q || busy) return;
    // Earlier answered turns, so a follow-up ("and in September?") makes sense.
    const history = turns
      .filter((t) => t.answer)
      .slice(-5)
      .flatMap((t) => [
        { role: "user", text: t.question },
        { role: "model", text: t.answer! },
      ]);
    setTurns((all) => [...all, { question: q }]);
    setQuestion("");
    setBusy(true);
    try {
      const response = await api<AskResponse>("/ask", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ question: q, history }),
      });
      setTurns((all) => all.map((t, i) => (i === all.length - 1 ? { ...t, ...response } : t)));
    } catch (e) {
      const error = (e as Error).message;
      setTurns((all) => all.map((t, i) => (i === all.length - 1 ? { ...t, error } : t)));
    } finally {
      setBusy(false);
    }
  }

  return (
    <>
      <h1 className="text-xl font-semibold">Ask</h1>
      <p className="max-w-2xl text-sm text-muted-foreground">
        Ask about your money in plain English. The AI only chooses what to look up; every
        number is calculated by the app, and &ldquo;How I got this&rdquo; under each answer
        shows exactly where it came from.
      </p>

      <Card>
        <CardContent className="flex flex-col gap-5">
          {turns.length === 0 && (
            <div className="flex flex-col gap-2 text-sm">
              <p className="text-muted-foreground">Try one of these:</p>
              <div className="flex flex-wrap gap-2">
                {SUGGESTIONS.map((s) => (
                  <Button key={s} variant="outline" size="sm" onClick={() => send(s)}>
                    {s}
                  </Button>
                ))}
              </div>
            </div>
          )}

          {turns.map((t, i) => (
            <div key={i} className="flex flex-col gap-2 text-sm">
              <p className="ml-auto max-w-[85%] rounded-2xl rounded-br-sm bg-primary px-3 py-2 text-primary-foreground">
                {t.question}
              </p>
              {t.error ? (
                <p className="max-w-[85%] text-destructive" role="alert">
                  {t.error}
                </p>
              ) : t.answer === undefined ? (
                <p className="text-muted-foreground" aria-live="polite">
                  Thinking…
                </p>
              ) : (
                <div className="flex max-w-[85%] flex-col gap-1.5">
                  <div className="rounded-2xl rounded-bl-sm bg-muted px-3 py-2">
                    <FormattedAnswer text={t.answer} />
                  </div>
                  {t.steps && t.steps.length > 0 && <HowIGotThis steps={t.steps} />}
                </div>
              )}
            </div>
          ))}
          <div ref={bottom} />

          <form
            className="flex gap-2"
            onSubmit={(e) => {
              e.preventDefault();
              send(question);
            }}
          >
            <Input
              value={question}
              onChange={(e) => setQuestion(e.target.value)}
              placeholder={turns.length ? "Ask a follow-up…" : "How much did I spend on dining in October?"}
              aria-label="Your question"
              maxLength={1000}
              disabled={busy}
            />
            <Button type="submit" disabled={busy || !question.trim()}>
              {busy ? "…" : "Ask"}
            </Button>
          </form>
          {turns.length > 0 && !busy && (
            <button
              type="button"
              className="self-start text-xs text-muted-foreground underline"
              onClick={() => setTurns([])}
            >
              Start a new conversation
            </button>
          )}
        </CardContent>
      </Card>
    </>
  );
}

/** The AI's answer with its light formatting: **bold**, and "- " or "1. " list lines. */
function FormattedAnswer({ text }: { text: string }) {
  const lines = text.trim().split("\n");
  return (
    <div className="flex flex-col gap-1">
      {lines.map((line, i) => {
        const item = /^\s*(?:[-*]|\d+\.)\s+(.*)$/.exec(line);
        const content = bold(item ? item[1] : line);
        if (!line.trim()) return null;
        return item ? (
          <p key={i} className="flex gap-1.5">
            <span aria-hidden>•</span>
            <span>{content}</span>
          </p>
        ) : (
          <p key={i}>{content}</p>
        );
      })}
    </div>
  );
}

function bold(line: string) {
  return line.split(/(\*\*[^*]+\*\*)/g).map((part, i) =>
    part.startsWith("**") && part.endsWith("**") ? (
      <strong key={i}>{part.slice(2, -2)}</strong>
    ) : (
      <span key={i}>{part}</span>
    ),
  );
}

function HowIGotThis({ steps }: { steps: AskStep[] }) {
  return (
    <details className="text-xs text-muted-foreground">
      <summary className="cursor-pointer select-none">How I got this</summary>
      <ol className="mt-1.5 flex flex-col gap-2 border-l pl-3">
        {steps.map((s, i) => (
          <li key={i} className="flex flex-col gap-0.5">
            <span className="font-medium text-foreground">
              {TOOL_NAMES[s.tool] ?? s.tool}
              {Object.keys(s.arguments).length > 0 && (
                <span className="font-normal text-muted-foreground"> · {describe(s.arguments)}</span>
              )}
            </span>
            <span className={cn("font-mono break-words", "error" in s.result && "text-destructive")}>
              {describe(s.result)}
            </span>
          </li>
        ))}
      </ol>
    </details>
  );
}

/** {"start_date": "2026-10-01", "spent": "$12.00"} -> "start date 2026-10-01, spent $12.00". */
function describe(values: Record<string, unknown>): string {
  return Object.entries(values)
    .map(([key, value]) => `${key.replaceAll("_", " ")} ${format(value)}`)
    .join(", ");
}

function format(value: unknown): string {
  if (Array.isArray(value)) {
    return `[${value.map((v) => (typeof v === "object" && v ? describe(v as Record<string, unknown>) : String(v))).join("; ")}]`;
  }
  if (typeof value === "object" && value) return `{${describe(value as Record<string, unknown>)}}`;
  return String(value);
}
