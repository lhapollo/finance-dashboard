from pathlib import Path

import pytest
from sqlalchemy import select

from app.models import RenameRule, Transaction

SAMPLE = (Path(__file__).parent / "fixtures" / "cibc_sample.csv").read_bytes()


@pytest.fixture
def presto(card, add):
    """Two Presto taps (same cleaned name, different raw text) and an unrelated purchase."""
    return (
        add(card, 13, -330, "PRESTO FARE/SSKF8NNDRM", cleaned_description="Presto Fare"),
        add(card, 14, -330, "PRESTO FARE/X81JD02KQA", cleaned_description="Presto Fare"),
        add(card, 15, -500, "HERO TEA", cleaned_description="Hero Tea"),
    )


def rename(client, t, **body):
    return client.patch(f"/transactions/{t.id}", json=body)


def test_rename_one(client, presto):
    first, second, _ = presto

    response = rename(client, first, description="  Presto  card ")

    assert response.status_code == 200
    assert response.json()["description"] == "Presto card"
    assert (first.description, first.description_source) == ("Presto card", "manual")
    assert first.cleaned_description == "Presto Fare"  # never edited
    assert second.description == "Presto Fare"


def test_rename_all_from_merchant(client, db_session, presto):
    first, second, other = presto

    rename(client, first, description="Presto", rename_all=True)

    assert [first.description, second.description] == ["Presto", "Presto"]
    assert first.description_source == second.description_source == "rule"
    assert other.description == "Hero Tea"
    rule = db_session.scalar(select(RenameRule))
    assert (rule.match, rule.name) == ("Presto Fare", "Presto")


def test_rename_all_skips_rows_renamed_by_hand(client, presto):
    first, second, _ = presto
    rename(client, second, description="Weekend trip")

    rename(client, first, description="Presto", rename_all=True)

    assert second.description == "Weekend trip"


def test_rename_all_from_a_hand_renamed_row_includes_it(client, presto):
    first, second, _ = presto
    rename(client, first, description="Typo")

    rename(client, first, description="Presto", rename_all=True)

    assert first.description == second.description == "Presto"


def test_renaming_again_updates_the_rule(client, db_session, presto):
    first, second, _ = presto
    rename(client, first, description="Presto", rename_all=True)

    rename(client, second, description="TTC & Presto", rename_all=True)

    assert first.description == "TTC & Presto"
    assert len(db_session.scalars(select(RenameRule)).all()) == 1


def test_renaming_back_to_original_removes_the_rule(client, db_session, presto):
    first, second, _ = presto
    rename(client, first, description="Presto", rename_all=True)

    rename(client, first, description="Presto Fare", rename_all=True)

    assert db_session.scalar(select(RenameRule)) is None
    assert second.description_source == "auto"


def test_null_description_undoes_a_rename(client, presto):
    first, _, _ = presto
    rename(client, first, description="Typo")

    body = rename(client, first, description=None).json()

    assert (body["description"], body["description_source"]) == ("Presto Fare", "auto")


def test_undoing_a_hand_rename_falls_back_to_the_rule(client, presto):
    first, second, _ = presto
    rename(client, second, description="Presto", rename_all=True)
    rename(client, first, description="One-off")

    rename(client, first, description=None)

    assert first.description == "Presto"


def test_blank_name_rejected(client, presto):
    assert rename(client, presto[0], description="   ").status_code == 422


def test_other_fields_leave_the_name_alone(client, presto):
    first, _, _ = presto
    rename(client, first, description="Presto")

    rename(client, first, category="transport")

    assert first.description == "Presto"


def test_new_imports_get_renamed(client, db_session, card):
    client.post("/import", data={"account_id": card.id}, files={"file": ("c.csv", SAMPLE)})
    loblaws = db_session.scalar(select(Transaction).where(Transaction.description == "Loblaws"))
    rename(client, loblaws, description="Groceries (Loblaws)", rename_all=True)
    db_session.delete(loblaws)  # pretend it wasn't imported yet
    db_session.flush()

    client.post("/import", data={"account_id": card.id}, files={"file": ("c.csv", SAMPLE)})

    again = db_session.scalar(
        select(Transaction).where(Transaction.cleaned_description == "Loblaws")
    )
    assert (again.description, again.description_source) == ("Groceries (Loblaws)", "rule")


def test_list_and_delete_rename_rules(client, presto):
    first, second, _ = presto
    rename(client, first, description="Presto", rename_all=True)

    rules = client.get("/rename-rules").json()
    assert [(r["match"], r["name"]) for r in rules] == [("Presto Fare", "Presto")]

    assert client.delete(f"/rename-rules/{rules[0]['id']}").status_code == 204
    assert first.description == second.description == "Presto Fare"
    assert client.delete(f"/rename-rules/{rules[0]['id']}").status_code == 404


def test_get_one_transaction(client, presto):
    body = client.get(f"/transactions/{presto[0].id}").json()

    assert body["raw_description"] == "PRESTO FARE/SSKF8NNDRM"
    assert "imported_at" in body
    assert client.get("/transactions/999999").status_code == 404
