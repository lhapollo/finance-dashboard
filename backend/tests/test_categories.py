import pytest

from app.models import Transaction
from app.services.categories import UNCATEGORIZED, apply_rules, categorize, load_rules


@pytest.fixture
def rules_file(tmp_path):
    def write(text, name="rules.yaml"):
        path = tmp_path / name
        path.write_text(text)
        return path

    return write


@pytest.mark.parametrize(
    "raw, expected",
    [
        ("LOBLAWS #1042 TORONTO, ON", "groceries"),
        ("T&T SUPERMARKET #020 RICHMOND HILL, ON", "groceries"),
        ("UBER CANADA/UBEREATS TORONTO, ON", "dining"),
        ("UBER CANADA/UBERTRIP TORONTO, ON", "transport"),
        ("DD/DOORDASHYOSUSHI VANCOUVER, BC", "dining"),
        ("WL *STEAM PURCHASE 425-889-9642, WA", "games"),
        ("HERO TEA WATERLOO, ON", "dining"),
        ("HONG DAE KOREAN RESTAU TORONTO, ON", "dining"),
        ("MCDONALD?S KING TORONTO, ON", "dining"),
        ("AMZN Mktp CA*530U81W10 866-216-1072, ON", "shopping"),
        ("DRIVE TEST PAYMENT TORONTO, ON", "transport"),
        ("ANNUAL FEE", "fees"),
        ("ANNUAL FEE REBATE", "fees"),
        ("CASHBACK/REMISE EN ARGENT", "rewards"),
        ("SOME LOCAL PLACE WATERLOO, ON", UNCATEGORIZED),
    ],
)
def test_committed_rules(raw, expected):
    assert categorize(raw, load_rules()) == expected


def test_whole_words_only(rules_file):
    rules = load_rules([rules_file("dining: [TEA]")])

    assert categorize("HERO TEA WATERLOO", rules) == "dining"
    assert categorize("STEAM PURCHASE", rules) == UNCATEGORIZED
    assert categorize("TEAM CANADA", rules) == UNCATEGORIZED


def test_trailing_star_matches_longer_words(rules_file):
    rules = load_rules([rules_file("dining: [DOORDASH*]")])

    assert categorize("DD/DOORDASHYOSUSHI", rules) == "dining"


def test_longest_pattern_wins(rules_file):
    rules = load_rules([rules_file("dining: [WUSA]\nshopping: [WUSA'S ONLINE SHOP]")])

    assert categorize("WUSA'S ONLINE SHOP WATERLOO, ON", rules) == "shopping"
    assert categorize("FLOCK STOP, WUSA WATERLOO, ON", rules) == "dining"


def test_later_file_wins_a_tie(rules_file):
    default = rules_file("entertainment: [SHOWCASE]", "default.yaml")
    personal = rules_file("shopping: [SHOWCASE]", "personal.yaml")

    assert categorize("SHOWCASE", load_rules([default, personal])) == "shopping"


def test_missing_file_is_skipped(tmp_path):
    assert load_rules([tmp_path / "nope.yaml"]) == []


@pytest.mark.parametrize("text", ["- just a list", "dining: TEA", "dining: [1, 2]"])
def test_malformed_file_is_rejected(rules_file, text):
    with pytest.raises(ValueError, match="rules.yaml"):
        load_rules([rules_file(text)])


def test_apply_rules_skips_manual_rows(db_session, card, add, rules_file):
    by_rule = add(card, 1, -500, "HERO TEA")
    by_hand = add(card, 2, -500, "HERO TEA", category="treats", category_source="manual")

    changed = apply_rules(db_session, load_rules([rules_file("dining: [TEA]")]))

    assert changed == 1
    assert by_rule.category == "dining"
    assert by_hand.category == "treats"


def test_apply_rules_uncategorizes_when_rule_removed(db_session, card, add):
    t = add(card, 1, -500, "HERO TEA", category="dining")

    apply_rules(db_session, [])

    assert t.category == UNCATEGORIZED


def test_patch_category_locks_it(client, db_session, card, add):
    t = add(card, 1, -500, "SOME LOCAL PLACE")

    response = client.patch(f"/transactions/{t.id}", json={"category": " Dining "})

    assert response.status_code == 200
    assert response.json()["category"] == "dining"
    assert t.category_source == "manual"
    client.post("/transactions/recategorize")
    assert t.category == "dining"


def test_patch_unmarking_a_transfer_unpairs_both_sides(client, db_session, card, add):
    a = add(card, 1, 5000, is_transfer=True)
    b = add(card, 2, -5000, is_transfer=True)
    a.transfer_pair_id, b.transfer_pair_id = b.id, a.id
    db_session.flush()

    response = client.patch(f"/transactions/{a.id}", json={"is_transfer": False})

    assert response.status_code == 200
    assert (a.is_transfer, a.transfer_pair_id, a.transfer_source) == (False, None, "manual")
    assert (b.is_transfer, b.transfer_pair_id) == (False, None)


def test_patch_marking_a_transfer(client, card, add):
    t = add(card, 1, -5000)

    body = client.patch(f"/transactions/{t.id}", json={"is_transfer": True}).json()

    assert body["is_transfer"] is True
    assert body["transfer_source"] == "manual"


def test_patch_only_changes_what_was_sent(client, card, add):
    t = add(card, 1, -500, "HERO TEA", category="dining")

    client.patch(f"/transactions/{t.id}", json={"is_transfer": True})

    assert (t.category, t.category_source) == ("dining", "rule")


@pytest.mark.parametrize("body", [{"category": "   "}, {"category": ""}])
def test_patch_rejects_blank_category(client, card, add, body):
    t = add(card, 1, -500)

    assert client.patch(f"/transactions/{t.id}", json=body).status_code == 422


def test_patch_unknown_transaction(client):
    assert client.patch("/transactions/999999", json={"category": "x"}).status_code == 404


def test_recategorize_endpoint(client, db_session, card, add):
    t = add(card, 1, -500, "LOBLAWS #1042 TORONTO, ON")

    response = client.post("/transactions/recategorize")

    assert response.json() == {"changed": 1}
    assert db_session.get(Transaction, t.id).category == "groceries"


def test_recategorize_reports_bad_rules_file(client, monkeypatch, tmp_path):
    from app.services import categories

    bad = tmp_path / "category_rules.yaml"
    bad.write_text("dining: TEA")
    monkeypatch.setattr(categories, "PERSONAL_RULES", bad)

    response = client.post("/transactions/recategorize")

    assert response.status_code == 400
    assert "should be a list" in response.json()["detail"]
