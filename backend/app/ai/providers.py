"""The one place that talks to an AI service.

The chat (app/ai/chat.py) speaks a small provider-neutral format: messages from the user,
replies from the model (text and/or tool calls), and tool results. Each provider translates
that to its own API. Switching to another provider (Claude, OpenAI, a local model through
Ollama) means adding a class here; nothing else changes.

Privacy: each provider says whether real financial data may be sent to it. Gemini's free
tier may use what it's sent to improve Google's models (and people may read it), so it's
only for the fake demo data unless AI_ALLOW_REAL_DATA is set on purpose.
"""

from dataclasses import dataclass, field
from typing import Any, Protocol

import httpx2 as httpx

from app import config


class AIError(Exception):
    """The AI service failed or refused; the message is safe to show."""


class AINotConfigured(AIError):
    pass


class AITimeout(AIError):
    """The service didn't answer in time (busy models sometimes hang); worth a retry."""


class RateLimited(AIError):
    """Too many requests for now. `retry_after` is how long the service says to wait."""

    def __init__(self, message: str, retry_after: float):
        super().__init__(message)
        self.retry_after = retry_after


@dataclass
class ToolCall:
    name: str
    arguments: dict[str, Any]
    id: str | None = None  # some providers match results to calls by id


@dataclass
class Message:
    role: str  # "user", "model", or "tool"
    text: str | None = None
    tool_calls: list[ToolCall] = field(default_factory=list)  # role "model"
    tool_results: list[tuple[ToolCall, dict[str, Any]]] = field(default_factory=list)  # "tool"
    # The provider's own copy of a model reply, sent back unchanged on the next request. Some
    # models attach hidden data (Gemini's "thought signatures") that must come back with it.
    raw: Any = None


@dataclass
class ToolSpec:
    name: str
    description: str
    parameters: dict[str, Any]  # JSON schema


class Provider(Protocol):
    name: str
    may_see_real_data: bool

    def reply(self, system: str, messages: list[Message], tools: list[ToolSpec]) -> Message: ...


class GeminiProvider:
    """Google's Gemini API (generateContent with function calling).
    Docs: https://ai.google.dev/gemini-api/docs/function-calling"""

    name = "gemini"
    may_see_real_data = False  # free tier: inputs may be used for training

    def __init__(self, api_key: str, model: str):
        if not api_key:
            raise AINotConfigured("the Ask page needs GEMINI_API_KEY in .env")
        self.model = model
        self._http = httpx.Client(
            base_url="https://generativelanguage.googleapis.com/v1beta",
            headers={"x-goog-api-key": api_key},
            # Busy models sometimes never answer; better to say so than to spin forever.
            timeout=30,
        )

    def reply(self, system: str, messages: list[Message], tools: list[ToolSpec]) -> Message:
        body = {
            "systemInstruction": {"parts": [{"text": system}]},
            "contents": [self._content(m) for m in messages],
            "tools": [
                {
                    "functionDeclarations": [
                        {"name": t.name, "description": t.description, "parameters": t.parameters}
                        for t in tools
                    ]
                }
            ],
            # Low randomness: the same question should get the same tool calls.
            "generationConfig": {"temperature": 0},
        }
        try:
            response = self._http.post(f"/models/{self.model}:generateContent", json=body)
        except httpx.TimeoutException as e:
            raise AITimeout("Gemini took too long to answer; try again") from e
        except httpx.HTTPError as e:
            raise AIError(f"couldn't reach Gemini: {e}") from e
        if response.status_code == 429:
            wait = _retry_delay(response.json())
            # A long wait means the free tier's daily allowance is used up, not just a burst.
            message = (
                f"Gemini's free daily limit is used up; try again in about {wait / 3600:.0f} hours"
                if wait > 300
                else "Gemini's free tier is busy (rate limit); try again in a minute"
            )
            raise RateLimited(message, wait)
        if response.status_code != 200:
            message = response.json().get("error", {}).get("message", response.text[:200])
            raise AIError(f"Gemini: {message}")

        candidates = response.json().get("candidates") or []
        if not candidates or "content" not in candidates[0]:
            reason = candidates[0].get("finishReason") if candidates else "no answer"
            raise AIError(f"Gemini didn't answer ({reason})")
        content = candidates[0]["content"]
        parts = content.get("parts", [])
        return Message(
            role="model",
            text="".join(p["text"] for p in parts if "text" in p and not p.get("thought")) or None,
            tool_calls=[
                ToolCall(
                    p["functionCall"]["name"],
                    p["functionCall"].get("args", {}),
                    p["functionCall"].get("id"),
                )
                for p in parts
                if "functionCall" in p
            ],
            raw=content,
        )

    @staticmethod
    def _content(m: Message) -> dict[str, Any]:
        if m.role == "user":
            return {"role": "user", "parts": [{"text": m.text}]}
        if m.role == "model":
            return m.raw or {"role": "model", "parts": [{"text": m.text or ""}]}
        return {
            "role": "user",
            "parts": [
                {
                    "functionResponse": {
                        "name": call.name,
                        "response": result,
                        **({"id": call.id} if call.id else {}),
                    }
                }
                for call, result in m.tool_results
            ],
        }


def get_provider() -> Provider:
    """The provider set in .env (AI_PROVIDER). Tests replace this with a fake."""
    if config.AI_PROVIDER == "gemini":
        return GeminiProvider(config.GEMINI_API_KEY, config.GEMINI_MODEL)
    raise AINotConfigured(f"unknown AI_PROVIDER {config.AI_PROVIDER!r}")


def _retry_delay(error_body: dict[str, Any]) -> float:
    """Gemini puts the wait in error.details as {"@type": "...RetryInfo", "retryDelay": "31s"}."""
    for detail in error_body.get("error", {}).get("details", []):
        delay = detail.get("retryDelay", "")
        if delay.endswith("s"):
            try:
                return float(delay[:-1])
            except ValueError:
                pass
    return 60.0
