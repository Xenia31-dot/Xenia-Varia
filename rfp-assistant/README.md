# RFP Assistant

A prototype RAG tool that drafts answers to RFI/RFP questionnaires from a company's own documents.
Answers come only from your documents. When they don't support an answer, the app says
**"No answer found"** instead of guessing.

## Setup

Python 3.11 or newer.

```bash
cd rfp-assistant
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
export ANTHROPIC_API_KEY=sk-ant-...      # never commit this
streamlit run app.py
```

The first run downloads the local embedding model (about 80 MB).

## Configuration (environment variables)

| Variable | Default | Meaning |
|---|---|---|
| `ANTHROPIC_API_KEY` | (required) | Claude API key |
| `RFP_MODEL` | `claude-opus-5-5` | Claude model used for drafting |
| `RFP_EFFORT` | `medium` | Claude effort level (`low`, `medium`, `high`) |
| `RFP_DATA_DIR` | `./data` | Where the Chroma database is stored |
| `RFP_EMBEDDER` | `default` | `default` = local all-MiniLM-L6-v2; `hashing` = offline test embedder |
| `RFP_TOP_K` | `6` | Document chunks retrieved per question |
| `RFP_BATCH_SIZE` | `5` | Questions drafted in parallel per batch |
| `RFP_MAX_RETRIES` | `4` | Retries for rate limits and server errors |
| `RFP_USE_FALLBACK` | `true` | Retry on a fallback model if a safety filter declines a benign question |

## Tests

```bash
python -m pytest -q
```

Tests use a fake Claude client and an offline embedder, so they need no API key or network.
