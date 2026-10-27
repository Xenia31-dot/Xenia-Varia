"""RFP Assistant: Streamlit UI. Business logic lives in the `rfp` package."""
from __future__ import annotations

import pandas as pd
import streamlit as st

from rfp.config import api_key_configured, get_settings
from rfp.embeddings import get_embedder
from rfp.generation import AnswerGenerator, DraftAnswer
from rfp.ingestion import SUPPORTED_EXTENSIONS, ingest_file
from rfp.prompts import NO_ANSWER
from rfp.retrieval import retrieve
from rfp.store import KnowledgeStore

st.set_page_config(page_title="RFP Assistant", page_icon="📝", layout="wide")
settings = get_settings()


@st.cache_resource(show_spinner="Loading the knowledge base…")
def get_store() -> KnowledgeStore:
    return KnowledgeStore(settings.data_dir / "chroma", get_embedder(settings.embedder))


@st.cache_resource
def get_generator() -> AnswerGenerator:
    return AnswerGenerator(settings)


store = get_store()
generator = get_generator()


def require_api_key() -> bool:
    if api_key_configured():
        return True
    st.error("Set the ANTHROPIC_API_KEY environment variable and restart the app to draft answers.")
    return False


# ------------------------------------------------------------------ sidebar

with st.sidebar:
    st.title("📝 RFP Assistant")
    st.caption("Drafts questionnaire answers from your own documents.")
    st.markdown(f"**Model:** `{settings.model}`  \n**Embeddings:** `{store.embedder.name}`")
    st.markdown("**API key:** " + ("✅ found" if api_key_configured() else "❌ missing"))
    docs = store.list_documents()
    st.metric("Indexed documents", len(docs))

tab_kb, tab_ask = st.tabs(["📚 Knowledge base", "💬 Ask a question"])

# ----------------------------------------------------------- knowledge base

with tab_kb:
    st.subheader("Upload company material")
    st.caption("PDF, Word and Excel files. Re-uploading a file with the same name replaces it.")
    uploads = st.file_uploader(
        "Documents",
        type=[e.lstrip(".") for e in sorted(SUPPORTED_EXTENSIONS)],
        accept_multiple_files=True,
        key="kb_upload",
    )
    if uploads and st.button("Index documents", type="primary"):
        progress = st.progress(0.0)
        for number, upload in enumerate(uploads, start=1):
            try:
                chunks = ingest_file(
                    upload.name, upload.getvalue(), settings.chunk_size, settings.chunk_overlap
                )
                if not chunks:
                    st.warning(f"{upload.name}: no text found (scanned PDF?).")
                else:
                    store.add_chunks(chunks)
                    st.success(f"{upload.name}: {len(chunks)} chunks indexed.")
            except Exception as exc:
                st.error(f"{upload.name}: could not be read ({exc}).")
            progress.progress(number / len(uploads))
        st.rerun()

    st.subheader("Indexed documents")
    docs = store.list_documents()
    if not docs:
        st.info("No documents yet.")
    for doc in docs:
        cols = st.columns([5, 3, 1, 1])
        cols[0].write(f"**{doc['source']}**")
        cols[1].write(doc["upload_date"])
        cols[2].write(f"{doc['chunks']} chunks")
        if cols[3].button("Delete", key=f"del-{doc['doc_id']}"):
            store.delete_document(doc["doc_id"])
            st.rerun()

# ------------------------------------------------------------- single question


def show_answer(draft: DraftAnswer) -> None:
    if draft.error:
        st.warning(draft.error)
    if draft.answer == NO_ANSWER:
        st.error(f"**{NO_ANSWER}** in the knowledge base. Flag for an SME.")
        return
    badge = {"high": "🟢", "medium": "🟡", "low": "🔴"}[draft.confidence]
    st.markdown(draft.answer)
    meta = f"{badge} Confidence: **{draft.confidence}**"
    if draft.compliance != "N/A":
        meta += f" · Compliance: **{draft.compliance}**"
    st.caption(meta)
    st.caption("Sources: " + "; ".join(draft.sources))


with tab_ask:
    st.subheader("Ask one question")
    question = st.text_area("Question", placeholder="Does the platform support single sign-on?")
    if st.button("Draft answer", type="primary", disabled=not question.strip()) and require_api_key():
        with st.spinner("Searching and drafting…"):
            sources = retrieve(store, question, settings)
            draft = generator.answer(question, sources)
        show_answer(draft)
        with st.expander(f"Retrieved sources ({len(sources)})"):
            st.dataframe(
                pd.DataFrame(
                    [
                        {"id": s.ref, "type": s.kind, "source": s.label,
                         "score": round(s.score, 3), "text": s.text}
                        for s in sources
                    ]
                ),
                hide_index=True,
            )
