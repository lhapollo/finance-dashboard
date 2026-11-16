"""Answering a question: the loop between the AI and the tools.

1. Send the question, the instructions and the tool list to the AI.
2. If it asks for tools, run them here and send back their results.
3. Repeat until it answers in words (or gives up after a few rounds).

Every tool call is kept as a "step", so the page can show how an answer was worked out.
"""

import json
from dataclasses import dataclass, field
from datetime import timedelta
from typing import Any

from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session

from app import config
from app.ai.providers import AIError, Message, Provider, ToolSpec
from app.ai.tools import TOOLS, TOOLS_BY_NAME, spending_categories
from app.services.clock import today

# Enough for "compare two things, then look something up", but a confused model can't loop
# forever (each round is a request to the AI service).
MAX_ROUNDS = 6


class PrivacyError(AIError):
    pass


@dataclass
class Step:
    tool: str
    arguments: dict[str, Any]
    result: dict[str, Any]


@dataclass
class Answer:
    text: str
    steps: list[Step] = field(default_factory=list)


def on_demo_data() -> bool:
    return (make_url(config.DATABASE_URL).database or "").endswith("_demo")


def check_privacy(provider: Provider) -> None:
    """Refuse before anything is sent: real finances only go to an approved provider."""
    if provider.may_see_real_data or on_demo_data() or config.AI_ALLOW_REAL_DATA:
        return
    raise PrivacyError(
        f"{provider.name} isn't approved for your real data (its free tier may use what it's "
        "sent for training), so Ask only works on the demo for now: "
        "docker compose --profile demo up -d, then http://localhost:3001/ask"
    )


def instructions(session: Session) -> str:
    day = today()
    last_month_end = day.replace(day=1) - timedelta(days=1)
    return f"""You answer questions about the user's personal finances, in Canadian dollars.

Today is {day:%A, %B %d, %Y} ({day.isoformat()}). "This month" is {day:%Y-%m}-01 to today;
"last month" is {last_month_end:%Y-%m}-01 to {last_month_end.isoformat()}. A month on its own
("in September") means the most recent one that isn't in the future.

Rules:
- Every number in your answer must come from a tool result. Never add, subtract, average or
  convert amounts yourself. If you need a number no tool gave you, call a tool that gives it
  (compare_spending works out differences and percent changes; can_i_afford checks budgets).
- Repeat amounts exactly as the tools write them.
- Say which dates you used, briefly ("in October 2026").
- Spending categories: {", ".join(spending_categories(session))}. Map everyday words to them:
  "food" is groceries and dining; "eating out" is dining.
- If a tool returns an error, fix the arguments and try again, or say what's missing.
- Keep answers short: one to three sentences, or a short list. No financial advice beyond
  what the numbers show."""


def ask(
    session: Session, provider: Provider, question: str, history: list[tuple[str, str]]
) -> Answer:
    """Answer `question`. `history` is earlier (role, text) turns, "user" or "model", so a
    follow-up like "and in September?" makes sense."""
    check_privacy(provider)
    system = instructions(session)
    specs = [ToolSpec(t.name, t.description, t.parameters) for t in TOOLS]
    messages = [Message(role=r, text=t) for r, t in history]
    messages.append(Message(role="user", text=question))
    steps: list[Step] = []

    for _ in range(MAX_ROUNDS):
        reply = provider.reply(system, messages, specs)
        messages.append(reply)
        if not reply.tool_calls:
            return Answer(text=reply.text or "I couldn't come up with an answer.", steps=steps)

        results = []
        for call in reply.tool_calls:
            tool = TOOLS_BY_NAME.get(call.name)
            result = (
                tool.call(session, call.arguments)
                if tool
                else {"error": f"there's no tool called {call.name}"}
            )
            # A round trip through JSON, so the AI gets exactly what the page shows.
            result = json.loads(json.dumps(result, default=str))
            steps.append(Step(call.name, call.arguments, result))
            results.append((call, result))
        messages.append(Message(role="tool", tool_results=results))

    return Answer(
        text="That took too many steps; try asking a simpler or more specific question.",
        steps=steps,
    )
