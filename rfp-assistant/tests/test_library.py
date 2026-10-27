from rfp import library
from rfp.ingestion import ingest_file
from rfp.prompts import NO_ANSWER
from rfp.retrieval import retrieve

from .helpers import make_pdf


def row(q, a, status="Approved", sources="a.pdf (page 1)"):
    return {"Question": q, "Draft answer": a, "Status": status, "Sources": sources}


def test_approved_answers_are_retrieved_before_documents(store, settings):
    store.add_chunks(ingest_file("sec.pdf", make_pdf(["Customer data encryption uses AES-256 at rest."])))
    library.approve(store, "Is customer data encrypted at rest?", "Yes, with AES-256.", "sec.pdf (page 1)")
    sources = retrieve(store, "Is customer data encrypted at rest?", settings)
    assert sources[0].kind == "library"
    assert sources[0].source == "Answer library"
    assert "Yes, with AES-256." in sources[0].text
    assert sources[1].kind == "document"


def test_unrelated_library_entries_are_not_used(store, settings):
    library.approve(store, "What is your refund policy for annual plans?", "30 days.")
    sources = retrieve(store, "Which SSO protocols are supported?", settings)
    assert all(s.kind != "library" for s in sources)


def test_no_answer_is_never_stored(store):
    assert library.approve(store, "Revenue?", NO_ANSWER) is None
    assert store.list_library() == []


def test_sync_adds_updates_and_removes(store):
    synced = library.sync_approved(store, [row("Q1?", "A1"), row("Q2?", "A2", "Draft")], {})
    assert [e["question"] for e in store.list_library()] == ["Q1?"]

    # edit an approved answer -> library updated
    synced = library.sync_approved(store, [row("Q1?", "A1 edited"), row("Q2?", "A2", "Draft")], synced)
    assert store.list_library()[0]["answer"] == "A1 edited"

    # un-approve -> removed again
    synced = library.sync_approved(store, [row("Q1?", "A1 edited", "Needs SME")], synced)
    assert store.list_library() == [] and synced == {}


def test_sync_leaves_entries_from_other_sessions_alone(store):
    library.approve(store, "Old question?", "Old answer")
    library.sync_approved(store, [row("New?", "New answer", "Draft")], {})
    assert [e["question"] for e in store.list_library()] == ["Old question?"]
