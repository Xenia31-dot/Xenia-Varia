from rfp.ingestion import ingest_file
from rfp.retrieval import retrieve

from .helpers import make_pdf, make_xlsx


def _index(store):
    store.add_chunks(ingest_file("security.pdf", make_pdf([
        "All customer data is encrypted at rest using AES-256 encryption.",
        "Our office has a nice coffee machine and plants.",
    ])))
    store.add_chunks(ingest_file("sla.xlsx", make_xlsx({"SLA": [["Metric", "Value"], ["Uptime", "99.95%"]]})))


def test_list_and_delete_documents(store):
    _index(store)
    docs = store.list_documents()
    assert [d["source"] for d in docs] == ["security.pdf", "sla.xlsx"]
    store.delete_document(docs[0]["doc_id"])
    assert [d["source"] for d in store.list_documents()] == ["sla.xlsx"]


def test_reupload_replaces_old_chunks(store):
    store.add_chunks(ingest_file("a.pdf", make_pdf(["one", "two", "three"])))
    store.add_chunks(ingest_file("a.pdf", make_pdf(["only one page now"])))
    assert store.list_documents()[0]["chunks"] == 1


def test_search_finds_relevant_chunk_first(store, settings):
    _index(store)
    sources = retrieve(store, "Is customer data encrypted at rest?", settings)
    assert sources[0].source == "security.pdf"
    assert sources[0].location == "page 1"
    assert [s.ref for s in sources] == [f"S{i}" for i in range(1, len(sources) + 1)]


def test_store_persists_on_disk(tmp_path):
    from rfp.embeddings import HashingEmbedder
    from rfp.store import KnowledgeStore

    path = tmp_path / "db"
    KnowledgeStore(path, HashingEmbedder()).add_chunks(ingest_file("x.pdf", make_pdf(["persist me"])))
    assert KnowledgeStore(path, HashingEmbedder()).list_documents()[0]["source"] == "x.pdf"
