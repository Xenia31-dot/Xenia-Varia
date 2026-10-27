"""Chroma wrapper. Two collections: raw document chunks and approved answers."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import chromadb
from chromadb.config import Settings as ChromaSettings

from .embeddings import Embedder
from .ingestion import Chunk


@dataclass
class Hit:
    id: str
    text: str
    metadata: dict
    score: float  # cosine similarity, higher is better


class KnowledgeStore:
    def __init__(self, path: str | Path, embedder: Embedder) -> None:
        self.embedder = embedder
        Path(path).mkdir(parents=True, exist_ok=True)
        self._client = chromadb.PersistentClient(
            path=str(path), settings=ChromaSettings(anonymized_telemetry=False)
        )
        # The embedder name is part of the collection name, so switching
        # embedders never mixes vectors of different sizes.
        self.documents = self._collection(f"documents_{embedder.name}")
        self.library = self._collection(f"library_{embedder.name}")

    def _collection(self, name: str):
        return self._client.get_or_create_collection(
            name=name, embedding_function=None, metadata={"hnsw:space": "cosine"}
        )

    # ------------------------------------------------------------ documents

    def add_chunks(self, chunks: list[Chunk], batch: int = 256) -> None:
        for doc_id in {c.metadata["doc_id"] for c in chunks}:
            self.delete_document(doc_id)
        for start in range(0, len(chunks), batch):
            part = chunks[start : start + batch]
            self.documents.upsert(
                ids=[c.id for c in part],
                documents=[c.text for c in part],
                metadatas=[c.metadata for c in part],
                embeddings=self.embedder.embed([c.text for c in part]),
            )

    def delete_document(self, doc_id: str) -> None:
        self.documents.delete(where={"doc_id": doc_id})

    def list_documents(self) -> list[dict]:
        result = self.documents.get(include=["metadatas"])
        docs: dict[str, dict] = {}
        for meta in result["metadatas"] or []:
            entry = docs.setdefault(
                meta["doc_id"],
                {
                    "doc_id": meta["doc_id"],
                    "source": meta["source"],
                    "upload_date": meta.get("upload_date", ""),
                    "chunks": 0,
                },
            )
            entry["chunks"] += 1
        return sorted(docs.values(), key=lambda d: d["source"].lower())

    def search_documents(self, query: str, k: int) -> list[Hit]:
        return self._search(self.documents, query, k)

    # -------------------------------------------------------------- library

    def upsert_library(self, entry_id: str, question: str, metadata: dict) -> None:
        self.library.upsert(
            ids=[entry_id],
            documents=[question],
            metadatas=[metadata],
            embeddings=self.embedder.embed([question]),
        )

    def delete_library(self, entry_id: str) -> None:
        self.library.delete(ids=[entry_id])

    def list_library(self) -> list[dict]:
        result = self.library.get(include=["metadatas", "documents"])
        rows = []
        for entry_id, question, meta in zip(
            result["ids"], result["documents"] or [], result["metadatas"] or []
        ):
            rows.append({"id": entry_id, "question": question, **meta})
        return sorted(rows, key=lambda r: r.get("approved_date", ""), reverse=True)

    def search_library(self, query: str, k: int) -> list[Hit]:
        return self._search(self.library, query, k)

    # --------------------------------------------------------------- shared

    def _search(self, collection, query: str, k: int) -> list[Hit]:
        count = collection.count()
        if count == 0 or not query.strip():
            return []
        result = collection.query(
            query_embeddings=self.embedder.embed([query]),
            n_results=min(k, count),
            include=["documents", "metadatas", "distances"],
        )
        return [
            Hit(id=i, text=t, metadata=m, score=1.0 - d)
            for i, t, m, d in zip(
                result["ids"][0],
                result["documents"][0],
                result["metadatas"][0],
                result["distances"][0],
            )
        ]
