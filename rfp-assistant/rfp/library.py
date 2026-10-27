"""Answer library: approved answers, reused first by retrieval."""
from __future__ import annotations

import hashlib
import re
from datetime import datetime, timezone

from .prompts import NO_ANSWER
from .store import KnowledgeStore


def entry_id(question: str) -> str:
    normalized = re.sub(r"\s+", " ", question.strip().lower())
    return "lib-" + hashlib.sha1(normalized.encode()).hexdigest()[:16]


def approve(store: KnowledgeStore, question: str, answer: str, sources: str = "") -> str | None:
    """Store an approved answer. Returns its id, or None if there is nothing to store."""
    answer = (answer or "").strip()
    if not question.strip() or not answer or answer == NO_ANSWER:
        return None
    eid = entry_id(question)
    store.upsert_library(
        eid,
        question.strip(),
        {
            "answer": answer,
            "sources": sources or "",
            "approved_date": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
        },
    )
    return eid


def remove(store: KnowledgeStore, eid: str) -> None:
    store.delete_library(eid)


def sync_approved(store: KnowledgeStore, rows: list[dict], synced: dict[str, str]) -> dict[str, str]:
    """Keep the library in line with the review table.

    rows: dicts with Question, Draft answer, Sources, Status.
    synced: {entry id: answer} that this review session already stored.
    Approved rows are added or updated. Rows this session approved and later
    moved back to Draft / Needs SME are removed again. Returns the new map.
    """
    current: dict[str, str] = {}
    for row in rows:
        if row.get("Status") != "Approved":
            continue
        question, answer = str(row.get("Question", "")), str(row.get("Draft answer", "")).strip()
        eid = entry_id(question)
        if synced.get(eid) != answer:
            eid = approve(store, question, answer, str(row.get("Sources", "") or ""))
        if eid:
            current[eid] = answer
    for eid in set(synced) - set(current):
        remove(store, eid)
    return current
