"""Check drafted answers against expected key facts.

    python -m eval.run_eval                      # full run (needs ANTHROPIC_API_KEY)
    python -m eval.run_eval --retrieval-only     # checks retrieval only, no API calls

The CSV has two columns:
  question        the question to answer
  expected_facts  facts separated by "|"; alternatives within one fact
                  separated by " OR "; or NO_ANSWER when the documents do
                  not contain the answer and the app must say so.

Matching is case-insensitive substring matching.
"""
from __future__ import annotations

import argparse
import csv
import sys
import tempfile
from dataclasses import replace
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from rfp.config import api_key_configured, get_settings  # noqa: E402
from rfp.embeddings import get_embedder  # noqa: E402
from rfp.generation import AnswerGenerator  # noqa: E402
from rfp.ingestion import SUPPORTED_EXTENSIONS, ingest_file  # noqa: E402
from rfp.prompts import NO_ANSWER  # noqa: E402
from rfp.retrieval import retrieve  # noqa: E402
from rfp.store import KnowledgeStore  # noqa: E402

HERE = Path(__file__).resolve().parent


def parse_facts(cell: str) -> list[list[str]]:
    return [[alt.strip() for alt in fact.split(" OR ") if alt.strip()]
            for fact in cell.split("|") if fact.strip()]


def fact_found(text: str, alternatives: list[str]) -> bool:
    lowered = " ".join(text.lower().split())
    return any(" ".join(alt.lower().split()) in lowered for alt in alternatives)


def score(answer: str, expected: str) -> tuple[bool, int, int, list[str]]:
    """Returns (passed, facts found, facts expected, missing facts)."""
    if expected.strip() == "NO_ANSWER":
        ok = answer.strip() == NO_ANSWER
        return ok, int(ok), 1, [] if ok else ["expected 'No answer found'"]
    facts = parse_facts(expected)
    missing = [" OR ".join(f) for f in facts if not fact_found(answer, f)]
    return not missing, len(facts) - len(missing), len(facts), missing


def build_store(docs_dir: Path, data_dir: Path, embedder_name: str) -> KnowledgeStore:
    store = KnowledgeStore(data_dir, get_embedder(embedder_name))
    files = [p for p in sorted(docs_dir.iterdir()) if p.suffix.lower() in SUPPORTED_EXTENSIONS]
    if not files:
        raise SystemExit(f"No documents found in {docs_dir}")
    for path in files:
        store.add_chunks(ingest_file(path.name, path.read_bytes()))
    print(f"Indexed {len(files)} documents from {docs_dir}")
    return store


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--questions", type=Path, default=HERE / "sample_questions.csv")
    parser.add_argument("--docs", type=Path, default=HERE / "sample_docs")
    parser.add_argument("--retrieval-only", action="store_true",
                        help="Check whether the facts appear in the retrieved chunks (no API calls)")
    parser.add_argument("--embedder", default=None, help="Override RFP_EMBEDDER")
    parser.add_argument("--out", type=Path, default=HERE / "results.csv")
    args = parser.parse_args(argv)

    settings = get_settings()
    if args.embedder:
        settings = replace(settings, embedder=args.embedder)
    if not args.retrieval_only and not api_key_configured():
        print("ANTHROPIC_API_KEY is not set. Set it, or use --retrieval-only.", file=sys.stderr)
        return 2

    with open(args.questions, newline="", encoding="utf-8") as f:
        cases = list(csv.DictReader(f))

    with tempfile.TemporaryDirectory() as tmp:
        store = build_store(args.docs, Path(tmp), settings.embedder)
        if args.retrieval_only:
            cases = [c for c in cases if c["expected_facts"].strip() != "NO_ANSWER"]
            answers = [
                "\n".join(s.text for s in retrieve(store, c["question"], settings)) for c in cases
            ]
            errors = [""] * len(cases)
        else:
            generator = AnswerGenerator(settings)
            drafts = generator.answer_many(
                [c["question"] for c in cases],
                lambda q: retrieve(store, q, settings),
                progress=lambda d, t: print(f"\r  drafted {d}/{t}", end="", flush=True),
            )
            print()
            answers = [d.answer for d in drafts]
            errors = [d.error for d in drafts]

    rows, passed, facts_found, facts_total = [], 0, 0, 0
    print()
    for case, answer, error in zip(cases, answers, errors):
        ok, found, total, missing = score(answer, case["expected_facts"])
        passed += ok
        facts_found += found
        facts_total += total
        mark = "PASS" if ok else "FAIL"
        print(f"[{mark}] {case['question']}")
        if not ok:
            print(f"        missing: {'; '.join(missing)}")
            if not args.retrieval_only:
                print(f"        answer:  {answer[:200]}")
        if error:
            print(f"        error:   {error}")
        rows.append({"question": case["question"], "expected_facts": case["expected_facts"],
                     "answer": answer if not args.retrieval_only else "",
                     "passed": ok, "facts_found": found, "facts_expected": total,
                     "missing": "; ".join(missing), "error": error})

    mode = "retrieved chunks" if args.retrieval_only else "answers"
    print(f"\n{passed}/{len(cases)} {mode} contain all expected facts "
          f"({facts_found}/{facts_total} facts found).")
    with open(args.out, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    print(f"Details written to {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
