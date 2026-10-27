"""Smoke test: the Streamlit app renders without errors."""
from pathlib import Path

from streamlit.testing.v1 import AppTest

APP = str(Path(__file__).resolve().parents[1] / "app.py")


def test_app_renders(tmp_path, monkeypatch):
    monkeypatch.setenv("RFP_EMBEDDER", "hashing")
    monkeypatch.setenv("RFP_DATA_DIR", str(tmp_path))
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    at = AppTest.from_file(APP, default_timeout=60).run()
    assert not at.exception
    assert any("RFP Assistant" in t.value for t in at.title)
