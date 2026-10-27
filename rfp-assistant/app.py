"""RFP Assistant: Streamlit UI. Business logic lives in the `rfp` package."""
from __future__ import annotations

import pandas as pd
import streamlit as st

from rfp.config import api_key_configured, get_settings
from rfp.embeddings import get_embedder
from rfp.export import STATUSES, review_table_to_excel, write_back_excel
from rfp.generation import AnswerGenerator, DraftAnswer
from rfp.ingestion import SUPPORTED_EXTENSIONS, ingest_file
from rfp.prompts import NO_ANSWER
from rfp.questionnaire import (
    ExcelLayout,
    column_label,
    detect_excel_layout,
    excel_preview,
    extract_excel_questions,
)
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

tab_kb, tab_q, tab_ask = st.tabs(
    ["📚 Knowledge base", "📋 Questionnaire", "💬 Ask a question"]
)

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


# ------------------------------------------------------------- questionnaire

ss = st.session_state


def build_review_table(questions, drafts) -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "_qid": q.id,
                "_row": q.location.get("row"),
                "Question": q.text,
                "Draft answer": d.answer,
                "Sources": "; ".join(d.sources),
                "Confidence": d.confidence if d.found else "low",
                "Status": d.status,
                "Notes": d.error,
            }
            for q, d in zip(questions, drafts)
        ]
    )


def excel_layout_editor(data: bytes, detected: ExcelLayout) -> ExcelLayout:
    """Let the user confirm or correct the detected sheet and columns."""
    preview = excel_preview(data)
    sheets = list(preview)
    c1, c2, c3, c4 = st.columns(4)
    sheet = c1.selectbox("Sheet", sheets, index=sheets.index(detected.sheet))
    rows = preview[sheet]
    header_row = c2.number_input(
        "Header row (0 = none)", min_value=0, max_value=max(len(rows), 1),
        value=detected.header_row if sheet == detected.sheet else 0,
    )
    width = max((len(r) for r in rows), default=1) + 1
    header = rows[header_row - 1] if header_row and header_row <= len(rows) else []
    labels = [column_label(c, header[c - 1] if c - 1 < len(header) else "") for c in range(1, width + 1)]
    q_default = detected.question_col if sheet == detected.sheet else 1
    a_default = detected.answer_col if sheet == detected.sheet else min(q_default + 1, width)
    q_col = c3.selectbox("Question column", range(1, width + 1), index=min(q_default, width) - 1,
                         format_func=lambda c: labels[c - 1])
    a_col = c4.selectbox("Answer column (for write-back)", range(1, width + 1),
                         index=min(a_default, width) - 1, format_func=lambda c: labels[c - 1])
    return ExcelLayout(sheet, int(header_row), int(q_col), int(a_col))


with tab_q:
    st.subheader("1. Upload a questionnaire")
    q_upload = st.file_uploader("Excel questionnaire", type=["xlsx", "xlsm"], key="q_upload")

    if q_upload is not None:
        file_key = f"{q_upload.name}-{q_upload.size}"
        if ss.get("q_file_key") != file_key:
            ss.q_file_key = file_key
            ss.q_name = q_upload.name
            ss.q_bytes = q_upload.getvalue()
            try:
                ss.q_detected = detect_excel_layout(ss.q_bytes)
            except Exception as exc:
                ss.q_detected = None
                st.error(f"Could not read this file: {exc}")

    if ss.get("q_bytes") and ss.get("q_detected"):
        st.subheader("2. Confirm the questions")
        st.caption("We guessed where the questions are. Correct the sheet or columns if needed, "
                   "and untick anything that is not a question.")
        layout = excel_layout_editor(ss.q_bytes, ss.q_detected)
        questions = extract_excel_questions(ss.q_bytes, layout)
        ss.q_layout = layout

        picked = st.data_editor(
            pd.DataFrame({"Include": True, "Cell": [q.id for q in questions],
                          "Question": [q.text for q in questions]}),
            hide_index=True, use_container_width=True,
            disabled=["Cell"], key=f"pick-{ss.q_file_key}-{layout}",
        )
        selected = []
        for q, row in zip(questions, picked.to_dict("records")):
            if row["Include"] and str(row["Question"]).strip():
                q.text = str(row["Question"]).strip()
                selected.append(q)
        st.write(f"**{len(selected)}** of {len(questions)} questions selected.")

        if st.button(f"Draft {len(selected)} answers", type="primary",
                     disabled=not selected) and require_api_key():
            bar = st.progress(0.0, text="Starting…")
            drafts = generator.answer_many(
                [q.text for q in selected],
                lambda text: retrieve(store, text, settings),
                progress=lambda done, total: bar.progress(done / total, text=f"Drafted {done} of {total}"),
            )
            ss.review_base = build_review_table(selected, drafts)
            ss.review_version = ss.get("review_version", 0) + 1
            ss.review_layout = layout
            ss.review_template = ss.q_bytes
            ss.review_name = ss.q_name
            bar.empty()

    if ss.get("review_base") is not None:
        st.subheader("3. Review and edit")
        edited = st.data_editor(
            ss.review_base,
            key=f"review-{ss.review_version}",
            hide_index=True,
            use_container_width=True,
            num_rows="fixed",
            column_config={
                "_qid": None,
                "_row": None,
                "Question": st.column_config.TextColumn(width="medium", disabled=True),
                "Draft answer": st.column_config.TextColumn(width="large"),
                "Sources": st.column_config.TextColumn(width="medium"),
                "Confidence": st.column_config.SelectboxColumn(
                    options=["high", "medium", "low"], disabled=True),
                "Status": st.column_config.SelectboxColumn(options=STATUSES, required=True),
                "Notes": st.column_config.TextColumn(disabled=True),
            },
        )
        counts = edited["Status"].value_counts()
        no_answer_count = int((edited["Draft answer"].str.strip() == NO_ANSWER).sum())
        m1, m2, m3, m4 = st.columns(4)
        m1.metric("Approved", int(counts.get("Approved", 0)))
        m2.metric("Draft", int(counts.get("Draft", 0)))
        m3.metric("Needs SME", int(counts.get("Needs SME", 0)))
        m4.metric("No answer found", no_answer_count)

        st.subheader("4. Export")
        base = ss.review_name.rsplit(".", 1)[0]
        d1, d2 = st.columns(2)
        d1.download_button(
            "Download review table (.xlsx)",
            review_table_to_excel(edited.drop(columns=["_qid", "_row"])),
            file_name=f"{base} - review.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )
        skip = d2.checkbox("Leave cells empty where no answer was found", value=True)
        answers = {int(r): a for r, a in zip(edited["_row"], edited["Draft answer"]) if pd.notna(r)}
        d2.download_button(
            "Download filled questionnaire (.xlsx)",
            write_back_excel(ss.review_template, ss.review_layout, answers, skip_no_answer=skip),
            file_name=f"{base} - answered.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )
