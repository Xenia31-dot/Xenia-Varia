"""Ask Claude to draft answers from retrieved sources, with retries and batching."""
from __future__ import annotations

import json
import logging
import random
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from typing import Callable

import anthropic

from .config import Settings
from .prompts import (
    ANSWER_SCHEMA,
    COMPLIANCE_SYSTEM,
    GENERAL_SYSTEM,
    NO_ANSWER,
    build_user_prompt,
    is_compliance_question,
)
from .retrieval import Source

log = logging.getLogger(__name__)

CONFIDENCE_ORDER = ["low", "medium", "high"]


class ModelRefusal(Exception):
    """The model (and its fallback) declined to answer."""


@dataclass
class DraftAnswer:
    question: str
    answer: str
    sources: list[str] = field(default_factory=list)  # "file (page 3)" labels
    confidence: str = "low"
    compliance: str = "N/A"
    status: str = "Draft"
    error: str = ""

    @property
    def found(self) -> bool:
        return self.answer != NO_ANSWER and not self.error


def no_answer(question: str, reason: str = "") -> DraftAnswer:
    return DraftAnswer(question=question, answer=NO_ANSWER, status="Needs SME", error=reason)


class AnswerGenerator:
    def __init__(self, settings: Settings, client: anthropic.Anthropic | None = None) -> None:
        self.settings = settings
        self._client = client

    @property
    def client(self) -> anthropic.Anthropic:
        if self._client is None:
            # Reads ANTHROPIC_API_KEY from the environment. The SDK itself
            # retries 429 / 5xx / connection errors with exponential backoff.
            self._client = anthropic.Anthropic(max_retries=self.settings.max_retries)
        return self._client

    # ------------------------------------------------------------ one answer

    def answer(self, question: str, sources: list[Source]) -> DraftAnswer:
        question = question.strip()
        if not question:
            return no_answer(question, "Empty question")
        if not sources:
            return no_answer(question)

        compliance = is_compliance_question(question)
        try:
            data = self._call_with_retry(question, sources, compliance)
        except anthropic.APIError as exc:
            log.warning("Claude API error for %r: %s", question[:60], exc)
            return no_answer(question, f"API error: {_short_error(exc)}")
        except ModelRefusal as exc:
            return no_answer(question, f"Refused: {exc}")
        except (ValueError, KeyError) as exc:
            return no_answer(question, f"Could not read the model's reply: {exc}")
        return self._to_draft(question, data, sources, compliance)

    def _call_with_retry(self, question: str, sources: list[Source], compliance: bool) -> dict:
        """The SDK retries transient HTTP errors; this adds a few extra attempts
        for rate limits, overloads and malformed replies."""
        attempts = 3
        for attempt in range(attempts):
            try:
                return self._call(question, sources, compliance)
            except (anthropic.RateLimitError, anthropic.InternalServerError,
                    anthropic.APIConnectionError, ValueError):
                if attempt == attempts - 1:
                    raise
                time.sleep(min(2 ** attempt * 2 + random.random(), 30))
        raise RuntimeError("unreachable")

    def _call(self, question: str, sources: list[Source], compliance: bool) -> dict:
        request = dict(
            model=self.settings.model,
            max_tokens=16000,
            system=COMPLIANCE_SYSTEM if compliance else GENERAL_SYSTEM,
            messages=[{"role": "user", "content": build_user_prompt(question, sources)}],
            output_config={
                "effort": self.settings.effort,
                "format": {"type": "json_schema", "schema": ANSWER_SCHEMA},
            },
        )
        if self.settings.use_fallback:
            # If a safety classifier declines a benign request, the API retries
            # it on a recommended fallback model instead of failing.
            response = self.client.beta.messages.create(
                **request, betas=["server-side-fallback-2026-07-01"], fallbacks="default"
            )
        else:
            response = self.client.messages.create(**request)

        if response.stop_reason == "refusal":
            raise ModelRefusal("the model declined this question")
        if response.stop_reason == "max_tokens":
            raise ValueError("reply was cut off")
        text = next((b.text for b in response.content if b.type == "text"), "")
        try:
            return json.loads(text)
        except json.JSONDecodeError as exc:
            raise ValueError("reply was not valid JSON") from exc

    def _to_draft(
        self, question: str, data: dict, sources: list[Source], compliance: bool
    ) -> DraftAnswer:
        by_ref = {s.ref: s for s in sources}
        cited = [by_ref[r] for r in dict.fromkeys(data.get("cited_sources", [])) if r in by_ref]
        answer = str(data.get("answer", "")).strip()

        # Guard rail: an answer must be supported AND cite at least one real source.
        if not data.get("supported") or not cited or not answer or answer == NO_ANSWER:
            return no_answer(question)

        confidence = data.get("confidence", "low")
        if confidence not in CONFIDENCE_ORDER:
            confidence = "low"
        level = data.get("compliance", "N/A") if compliance else "N/A"

        labels = list(dict.fromkeys(s.label for s in cited))
        return DraftAnswer(
            question=question,
            answer=answer,
            sources=labels,
            confidence=confidence,
            compliance=level,
            status="Needs SME" if confidence == "low" else "Draft",
        )

    # ---------------------------------------------------------- many answers

    def answer_many(
        self,
        questions: list[str],
        retrieve_fn: Callable[[str], list[Source]],
        progress: Callable[[int, int], None] | None = None,
    ) -> list[DraftAnswer]:
        """Answer questions in batches. Within a batch, calls run in parallel.
        One failed question never stops the run."""
        results: list[DraftAnswer | None] = [None] * len(questions)
        size = max(1, self.settings.batch_size)
        done = 0

        def work(index: int) -> tuple[int, DraftAnswer]:
            question = questions[index]
            try:
                return index, self.answer(question, retrieve_fn(question))
            except Exception as exc:  # keep going; the row is flagged for review
                log.exception("Failed to answer %r", question[:60])
                return index, no_answer(question, f"Unexpected error: {exc}")

        with ThreadPoolExecutor(max_workers=size) as pool:
            for start in range(0, len(questions), size):
                for index, draft in pool.map(work, range(start, min(start + size, len(questions)))):
                    results[index] = draft
                    done += 1
                    if progress:
                        progress(done, len(questions))
        return [r for r in results if r is not None]


def _short_error(exc: Exception) -> str:
    status = getattr(exc, "status_code", None)
    message = getattr(exc, "message", None) or str(exc)
    return f"{status} {message}" if status else message
