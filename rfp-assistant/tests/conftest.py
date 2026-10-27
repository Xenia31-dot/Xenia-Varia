import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from rfp.config import Settings  # noqa: E402
from rfp.embeddings import HashingEmbedder  # noqa: E402
from rfp.store import KnowledgeStore  # noqa: E402


@pytest.fixture
def settings(tmp_path):
    return Settings(data_dir=tmp_path, embedder="hashing", batch_size=3, library_min_score=0.6)


@pytest.fixture
def store(tmp_path):
    return KnowledgeStore(tmp_path / "chroma", HashingEmbedder())
