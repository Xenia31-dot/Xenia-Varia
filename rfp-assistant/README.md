# RFP Assistant

A prototype RAG tool that drafts answers to RFI/RFP questionnaires from a company's own documents.

1. Upload your product, marketing and technical material (PDF, Word, Excel).
2. Upload a questionnaire (Excel or Word). Confirm which cells or paragraphs are questions.
3. Claude drafts an answer for every question, **using only your documents**, with sources and
   a confidence level. When the documents don't support an answer, it says **"No answer found"**
   instead of guessing.
4. Review and edit the answers in a table, mark them Approved or Needs SME, and download the
   result, either as a review table or written back into the original questionnaire.
5. Approved answers go into an **answer library**, which is searched first next time.

## Setup

Python 3.11 or newer.

```bash
cd rfp-assistant
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
export ANTHROPIC_API_KEY=sk-ant-...      # never commit this
streamlit run app.py
```

The first run downloads the local embedding model (about 80 MB). Data is stored in `./data`.

## Try it with the sample files

The repo includes a small knowledge base and two questionnaires for a fictional company,
"Nimbus Analytics" (regenerate them with `python -m eval.make_samples`).

1. **Knowledge base** tab: upload the three files in `eval/sample_docs/` and click *Index documents*.
2. **Questionnaire** tab: upload `eval/sample_questionnaires/Sample RFP.xlsx`. The app detects
   the *Questions* sheet, column C as questions and column D as the answer column.
   Click *Draft 12 answers*.
3. Edit answers in the table, set *Status* to Approved for good ones, then download the
   review table or the filled questionnaire.
4. **Answer library** tab: approved answers appear here.
5. Repeat step 2 with `Sample Due Diligence.docx` to try Word (paragraph and table questions).

Two sample questions (company revenue, on-site training in Japan) have no answer in the
documents on purpose; they should come back as "No answer found".

## How it works

```
rfp-assistant/
  app.py                 Streamlit UI only
  rfp/
    config.py            settings from environment variables
    ingestion.py         PDF/Word/Excel -> chunks with file name, page/sheet/section, upload date
    embeddings.py        Embedder interface: local MiniLM (default) or offline hashing
    store.py             Chroma (persistent): documents + answer library collections
    retrieval.py         approved answers first, then document chunks
    prompts.py           all prompts, the answer JSON schema, the compliance heuristic
    generation.py        Claude calls, guard rails, retries, batching
    questionnaire.py     question detection for Excel and Word
    export.py            review-table Excel, write-back into Excel and Word templates
    library.py           approve / sync / remove library answers
  eval/                  sample data and the evaluation script
  tests/                 pytest suite (no API key or network needed)
```

**Answer drafting.** For each question the app retrieves up to 3 similar approved answers
and the top 6 document chunks. It sends them to Claude with instructions to use only those
sources. Claude replies in a fixed JSON format (answer, supported yes/no, cited source ids,
confidence, compliance level). The code then enforces the rules: an answer that isn't marked
supported, or that cites no real source, is replaced with "No answer found" and set to
*Needs SME*. Low-confidence answers are also set to *Needs SME*.

**Compliance questions.** Yes/no questions ("Does…", "Is…", "Can…") and questions that mention
compliance or certification get a stricter prompt. The answer starts with *Fully supported*,
*Partially supported* or *Not supported*, followed by a short justification. "Not supported"
requires a source that says so; silence in the documents gives "No answer found" instead.

**Batches and errors.** Questions are drafted in batches (5 at a time, in parallel) with a
progress bar. The Anthropic SDK retries rate limits, server errors and connection errors with
exponential backoff, and the app adds a few more attempts on top. A question that still fails
is marked *⚠️ Error* with the reason in *Notes*; the rest of the run continues.

**Answer library.** Setting a row to *Approved* saves it right away. Editing an approved answer
updates the saved entry, and changing the status back removes it. Retrieval puts library entries
first and labels them "approved answer", and the prompt tells Claude to prefer them.

**Swapping the embedding model.** Write a class with a `name` and an
`embed(texts) -> list[list[float]]` method in `rfp/embeddings.py` and register it in
`get_embedder()`. Each embedder gets its own Chroma collections, so switching never mixes
vectors. Documents must be re-uploaded after a switch.

## Configuration (environment variables)

| Variable | Default | Meaning |
|---|---|---|
| `ANTHROPIC_API_KEY` | (required) | Claude API key |
| `RFP_MODEL` | `claude-opus-5-5` | Claude model used for drafting |
| `RFP_EFFORT` | `medium` | Claude effort level (`low`, `medium`, `high`) |
| `RFP_DATA_DIR` | `./data` | Where the Chroma database is stored |
| `RFP_EMBEDDER` | `default` | `default` = local all-MiniLM-L6-v2; `hashing` = offline test embedder |
| `RFP_TOP_K` | `6` | Document chunks retrieved per question |
| `RFP_LIBRARY_MIN_SCORE` | `0.55` | Minimum question similarity for a library answer to be used |
| `RFP_BATCH_SIZE` | `5` | Questions drafted in parallel per batch |
| `RFP_MAX_RETRIES` | `4` | SDK retries for rate limits and server errors |
| `RFP_USE_FALLBACK` | `true` | If a safety filter declines a benign question, retry it on a fallback model |

## Tests

```bash
python -m pytest -q
```

Tests use a fake Claude client and an offline embedder, so they need no API key or network.

## Evaluation

`eval/sample_questions.csv` lists questions and the key facts each answer must contain
(`|` between facts, ` OR ` between acceptable alternatives, `NO_ANSWER` when the documents
don't have the answer and the app must say so).

```bash
python -m eval.run_eval                    # drafts real answers (needs ANTHROPIC_API_KEY)
python -m eval.run_eval --retrieval-only   # checks only that retrieval finds the facts
python -m eval.run_eval --questions my_questions.csv --docs path/to/my_docs
```

It prints PASS/FAIL per question, the number of answers that contain all expected facts,
and writes details to `eval/results.csv`.

## Known limits (prototype)

- Scanned PDFs need OCR first; the app only reads PDFs that contain text.
- Word write-back adds a paragraph after each question; complex layouts (content controls,
  nested tables) are not handled.
- Data is stored locally with no user accounts or access control.
- The compliance-question check is a keyword heuristic.
