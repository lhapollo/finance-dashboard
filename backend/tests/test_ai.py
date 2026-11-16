"""The Ask page: tools, the chat loop, the privacy guard, and the Gemini adapter.

No real AI is called: a scripted fake stands in for the model, and Gemini's web API is
replaced by a fake server.
"""

import json
import random
from datetime import date

import httpx2 as httpx
import pytest

from app import config
from app.ai import chat
from app.ai.providers import GeminiProvider, Message, RateLimited, ToolCall, ToolSpec
from app.ai.tools import TOOLS_BY_NAME
from app.demo import seed
from app.main import app
from app.routers.ask import provider_dependency

DAY = date(2026, 11, 15)


@pytest.fixture
def demo(db_session, monkeypatch):
    """The fake demo year, with "today" pinned so answers don't move."""
    seed(db_session, DAY, random.Random(2026))
    db_session.flush()
    monkeypatch.setattr(chat, "today", lambda: DAY)
    monkeypatch.setattr(config, "DATABASE_URL", "postgresql+psycopg://u:p@db/finance_demo")


def run(db_session, name, **arguments):
    return TOOLS_BY_NAME[name].call(db_session, arguments)


# --- tools ---


def test_spending_matches_the_dashboard(client, db_session, demo):
    month = client.get("/summary/month?month=2026-10").json()
    result = run(db_session, "get_spending", start_date="2026-10-01", end_date="2026-10-31")
    assert result["spent"] == f"${month['spent_cents'] / 100:,.2f}"


def test_spending_by_category_and_merchant(db_session, demo):
    food = run(
        db_session,
        "get_spending",
        start_date="2026-10-01",
        end_date="2026-10-31",
        categories=["groceries", "dining"],
    )
    groceries = run(
        db_session,
        "get_spending",
        start_date="2026-10-01",
        end_date="2026-10-31",
        categories=["groceries"],
    )
    tims = run(
        db_session,
        "get_spending",
        start_date="2026-10-01",
        end_date="2026-10-31",
        merchant="tim hortons",
    )
    as_cents = lambda s: int(round(float(s.replace("$", "").replace(",", "")) * 100))  # noqa: E731
    assert as_cents(food["spent"]) > as_cents(groceries["spent"]) > 0
    assert tims["purchases"] > 0 and tims["merchant"] == "tim hortons"


def test_a_shared_dinner_counts_only_my_half(db_session, demo):
    keg = run(
        db_session, "get_spending", start_date="2026-10-01", end_date="2026-11-15", merchant="Keg"
    )
    assert keg["spent"] == "$60.00"  # $120 dinner, friend paid back $60


def test_compare_works_out_the_difference(db_session, demo):
    result = run(
        db_session,
        "compare_spending",
        first_start_date="2026-09-01",
        first_end_date="2026-09-30",
        second_start_date="2026-10-01",
        second_end_date="2026-10-31",
        categories=["dining"],
    )
    assert result["first_period"] == "September 2026"
    assert result["comparison"].startswith("October 2026: $")
    assert " than September 2026 ($" in result["comparison"]
    assert result["comparison"].endswith(("% more", "% less"))


def test_mistakes_come_back_as_errors_the_ai_can_fix(db_session, demo):
    unknown = run(
        db_session,
        "get_spending",
        start_date="2026-10-01",
        end_date="2026-10-31",
        categories=["food"],
    )
    assert "unknown categories ['food']" in unknown["error"]
    assert "groceries" in unknown["error"]
    backwards = run(db_session, "get_spending", start_date="2026-10-31", end_date="2026-10-01")
    assert "end_date is before start_date" in backwards["error"]
    missing = run(db_session, "get_income", start_date="2026-10-01")
    assert "end_date" in missing["error"]


def test_can_i_afford(db_session, demo):
    yes = run(db_session, "can_i_afford", amount_dollars=10, bucket="switch")
    assert (yes["bucket"], yes["enough_in_bucket"]) == ("Switch 2", True)
    no = run(db_session, "can_i_afford", amount_dollars=999_999, bucket="Switch 2")
    assert no["enough_with_unassigned_too"] is False and no["short_by"] != "$0.00"
    unknown = run(db_session, "can_i_afford", amount_dollars=10, bucket="Vacation")
    assert "Rent" in unknown["error"]


def test_budget_balances_and_lookups(db_session, demo):
    budget = run(db_session, "get_budget")
    assert {b["name"] for b in budget["buckets"]} >= {"Rent", "Switch 2"}
    balances = run(db_session, "get_balances")
    assert balances["available"].startswith("$")
    found = run(db_session, "find_transactions", search="netflix", limit=2)
    assert len(found["transactions"]) == 2
    assert all("Netflix" in t["description"] for t in found["transactions"])


# --- the chat loop ---


class FakeModel:
    """Plays back scripted replies, and records what it was sent."""

    name = "fake"
    may_see_real_data = False

    def __init__(self, *replies: Message):
        self.replies = list(replies)
        self.sent: list[list[Message]] = []

    def reply(self, system, messages, tools):
        self.sent.append(list(messages))
        self.system = system
        return self.replies.pop(0)


@pytest.fixture
def model(monkeypatch):
    fake = FakeModel()
    app.dependency_overrides[provider_dependency] = lambda: fake
    return fake


def test_the_loop_runs_tools_and_returns_the_answer(client, demo, model):
    model.replies = [
        Message(
            role="model",
            tool_calls=[
                ToolCall("get_spending", {"start_date": "2026-10-01", "end_date": "2026-10-31"})
            ],
        ),
        Message(role="model", text="You spent $X in October 2026."),
    ]
    response = client.post("/ask", json={"question": "How much did I spend in October?"})
    body = response.json()
    assert response.status_code == 200, body
    assert body["answer"] == "You spent $X in October 2026."
    [step] = body["steps"]
    assert step["tool"] == "get_spending" and step["result"]["spent"].startswith("$")
    # The tool's result went back to the model before it answered.
    tool_message = model.sent[1][-1]
    assert tool_message.role == "tool" and tool_message.tool_results[0][1] == step["result"]
    assert "Today is Sunday, November 15, 2026" in model.system


def test_history_is_sent_for_follow_ups(client, demo, model):
    model.replies = [Message(role="model", text="ok")]
    client.post(
        "/ask",
        json={
            "question": "and in September?",
            "history": [
                {"role": "user", "text": "dining in October?"},
                {"role": "model", "text": "$300"},
            ],
        },
    )
    assert [m.text for m in model.sent[0]] == ["dining in October?", "$300", "and in September?"]


def test_the_loop_gives_up_eventually(client, demo, model):
    call = ToolCall("get_budget", {})
    model.replies = [Message(role="model", tool_calls=[call]) for _ in range(chat.MAX_ROUNDS)]
    body = client.post("/ask", json={"question": "?"}).json()
    assert "too many steps" in body["answer"]
    assert len(body["steps"]) == chat.MAX_ROUNDS


def test_real_data_never_goes_to_an_unapproved_model(client, model, monkeypatch):
    monkeypatch.setattr(config, "DATABASE_URL", "postgresql+psycopg://u:p@db/finance")
    response = client.post("/ask", json={"question": "How much did I spend?"})
    assert response.status_code == 403
    assert "demo" in response.json()["detail"]
    assert model.sent == []  # nothing was sent

    monkeypatch.setattr(config, "AI_ALLOW_REAL_DATA", True)
    model.replies = [Message(role="model", text="ok")]
    assert client.post("/ask", json={"question": "?"}).status_code == 200


# --- the Gemini adapter ---


def test_gemini_request_and_reply_shapes():
    seen = {}

    def server(request: httpx.Request) -> httpx.Response:
        seen["path"] = request.url.path
        seen["key"] = request.headers["x-goog-api-key"]
        seen["body"] = json.loads(request.content)
        return httpx.Response(
            200,
            json={
                "candidates": [
                    {
                        "content": {
                            "role": "model",
                            "parts": [
                                {
                                    "functionCall": {"name": "get_budget", "args": {}},
                                    "thoughtSignature": "abc",
                                }
                            ],
                        }
                    }
                ]
            },
        )

    gemini = GeminiProvider("test-key", "gemini-test")
    gemini._http = httpx.Client(
        base_url="https://example.test/v1beta",
        headers={"x-goog-api-key": "test-key"},
        transport=httpx.MockTransport(server),
    )
    tools = [
        ToolSpec("get_budget", "The budget", {"type": "object", "properties": {}, "required": []})
    ]
    reply = gemini.reply("be brief", [Message(role="user", text="budget?")], tools)

    assert seen["path"] == "/v1beta/models/gemini-test:generateContent"
    assert seen["key"] == "test-key"
    assert seen["body"]["systemInstruction"]["parts"][0]["text"] == "be brief"
    assert seen["body"]["tools"][0]["functionDeclarations"][0]["name"] == "get_budget"
    assert reply.tool_calls == [ToolCall("get_budget", {}, None)]

    # The model's reply goes back unchanged (with its thought signature), and the tool result
    # is a functionResponse.
    gemini.reply(
        "be brief",
        [
            Message(role="user", text="budget?"),
            reply,
            Message(role="tool", tool_results=[(reply.tool_calls[0], {"unassigned": "$1.00"})]),
        ],
        tools,
    )
    contents = seen["body"]["contents"]
    assert contents[1]["parts"][0]["thoughtSignature"] == "abc"
    assert contents[2]["parts"][0]["functionResponse"] == {
        "name": "get_budget",
        "response": {"unassigned": "$1.00"},
    }


def test_gemini_rate_limit_is_explained():
    gemini = GeminiProvider("k", "m")
    gemini._http = httpx.Client(
        base_url="https://example.test",
        transport=httpx.MockTransport(lambda r: httpx.Response(429, json={})),
    )
    with pytest.raises(RateLimited, match="rate limit") as caught:
        gemini.reply("", [Message(role="user", text="hi")], [])
    assert caught.value.retry_after == 60.0  # no RetryInfo in this response


def test_no_key_is_explained(monkeypatch):
    monkeypatch.setattr(config, "GEMINI_API_KEY", "")
    with pytest.raises(chat.AIError, match="GEMINI_API_KEY"):
        GeminiProvider(config.GEMINI_API_KEY, "m")


# --- the eval's grading ---


def test_eval_grading_is_strict():
    from app.ai.eval import passes

    assert passes("You spent $1,007.35 in October.", ["$1,007.35"])
    assert not passes("You spent about $1,007 in October.", ["$1,007.35"])
    assert passes("No, the Switch 2 bucket only has $340.50.", ["no"])
    assert not passes("I don't know.", ["no"])  # "no" inside "know" doesn't count
    assert passes("Groceries and Dining are overspent.", ["Groceries", "Dining"])
    assert passes("You cannot pay for a $5,000.00 trip.", ["no"])
    assert passes("Yes, you can afford it.", ["yes"])
    assert not passes("You can afford it.", ["no"])
    assert passes("The most went to Riverside Properties.", ["e-Transfer to Riverside Properties"])


def test_eval_questions_have_answers_on_the_demo(db_session, demo, monkeypatch):
    from app.ai import eval as evaluation

    monkeypatch.setattr(evaluation, "today", lambda: DAY)
    for case in evaluation._cases():
        expected = case.expected(db_session)
        assert expected and all(isinstance(e, str) and e for e in expected), case.question


def test_gemini_timeouts_are_explained():
    from app.ai.providers import AITimeout

    def hang(request):
        raise httpx.ReadTimeout("slow", request=request)

    gemini = GeminiProvider("k", "m")
    gemini._http = httpx.Client(
        base_url="https://example.test", transport=httpx.MockTransport(hang)
    )
    with pytest.raises(AITimeout, match="took too long"):
        gemini.reply("", [Message(role="user", text="hi")], [])
