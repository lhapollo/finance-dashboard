"""Notes I write on transactions."""


def note(client, t, value):
    return client.patch(f"/transactions/{t.id}", json={"note": value})


def test_a_note_is_saved_tidied_and_returned(client, card, add):
    t = add(card, 1, -25000, "LENSCRAFTERS")

    body = note(client, t, "  new glasses, half covered by insurance \n").json()

    assert body["note"] == "new glasses, half covered by insurance"
    assert t.note == "new glasses, half covered by insurance"


def test_a_blank_or_null_note_removes_it(client, card, add):
    t = add(card, 1, -500, note="old note")
    assert note(client, t, "   ").json()["note"] is None

    t.note = "old note"
    assert note(client, t, None).json()["note"] is None


def test_other_changes_leave_the_note_alone(client, card, add):
    t = add(card, 1, -500, "HERO TEA", note="with Sam")

    client.patch(f"/transactions/{t.id}", json={"category": "dining"})

    assert t.note == "with Sam"


def test_a_note_can_be_at_most_500_characters(client, card, add):
    t = add(card, 1, -500)

    assert note(client, t, "x" * 500).status_code == 200
    assert note(client, t, "x" * 501).status_code == 422


def test_search_finds_words_in_notes(client, card, add):
    glasses = add(card, 1, -25000, "LENSCRAFTERS", note="New glasses")
    add(card, 2, -500, "HERO TEA")

    found = client.get("/transactions", params={"search": "glasses"}).json()

    assert [t["id"] for t in found["items"]] == [glasses.id]
