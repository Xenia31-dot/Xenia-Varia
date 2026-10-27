"""Find the sources for a question. Approved library answers come first."""
from __future__ import annotations

from dataclasses import dataclass

from .config import Settings
from .store import KnowledgeStore


@dataclass
class Source:
    ref: str  # short id shown to the model, e.g. "S1"
    kind: str  # "library" or "document"
    text: str
    source: str  # file name, or "Answer library"
    location: str  # page / sheet / section, or the approved question
    score: float

    @property
    def label(self) -> str:
        return f"{self.source} ({self.location})"


def retrieve(store: KnowledgeStore, question: str, settings: Settings) -> list[Source]:
    sources: list[Source] = []

    for hit in store.search_library(question, settings.library_k):
        if hit.score < settings.library_min_score:
            continue
        meta = hit.metadata
        sources.append(
            Source(
                ref="",
                kind="library",
                text=(
                    f"Previously approved answer to the question: {hit.text}\n"
                    f"Answer: {meta.get('answer', '')}\n"
                    f"Original sources: {meta.get('sources', '')}"
                ),
                source="Answer library",
                location=f"approved {meta.get('approved_date', '')}".strip(),
                score=hit.score,
            )
        )

    for hit in store.search_documents(question, settings.top_k):
        meta = hit.metadata
        sources.append(
            Source(
                ref="",
                kind="document",
                text=hit.text,
                source=meta.get("source", "unknown"),
                location=meta.get("location", ""),
                score=hit.score,
            )
        )

    for number, source in enumerate(sources, start=1):
        source.ref = f"S{number}"
    return sources
