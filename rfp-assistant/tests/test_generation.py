import anthropic
import httpx

from rfp.generation import AnswerGenerator
from rfp.prompts import COMPLIANCE_SYSTEM, NO_ANSWER, is_compliance_question
from rfp.retrieval import Source

from .helpers import FakeClient

SOURCES = [
    Source("S1", "document", "Data is encrypted at rest with AES-256.", "security.pdf", "page 2", 0.8),
    Source("S2", "document", "Uptime SLA is 99.95%.", "sla.xlsx", "sheet 'SLA' rows 2-2", 0.4),
]


def reply(**overrides):
    base = {"answer": "We encrypt data at rest with AES-256.", "supported": True,
            "cited_sources": ["S1"], "confidence": "high", "compliance": "N/A"}
    base.update(overrides)
    return base


def gen(settings, responder):
    client = FakeClient(responder)
    return AnswerGenerator(settings, client=client), client


def test_supported_answer_has_sources_and_confidence(settings):
    g, _ = gen(settings, lambda s, u: reply())
    draft = g.answer("How is data protected at rest?", SOURCES)
    assert draft.answer.startswith("We encrypt")
    assert draft.sources == ["security.pdf (page 2)"]
    assert draft.confidence == "high"
    assert draft.status == "Draft"


def test_unsupported_answer_becomes_no_answer(settings):
    g, _ = gen(settings, lambda s, u: reply(supported=False, answer="Probably yes", cited_sources=[]))
    draft = g.answer("Do you have a FedRAMP authorization?", SOURCES)
    assert draft.answer == NO_ANSWER
    assert draft.status == "Needs SME"


def test_answer_citing_unknown_sources_is_rejected(settings):
    g, _ = gen(settings, lambda s, u: reply(cited_sources=["S9"]))
    assert g.answer("Encryption?", SOURCES).answer == NO_ANSWER


def test_no_sources_skips_the_api(settings):
    g, client = gen(settings, lambda s, u: reply())
    assert g.answer("Anything?", []).answer == NO_ANSWER
    assert client.calls == []


def test_compliance_question_uses_strict_prompt(settings):
    g, client = gen(settings, lambda s, u: reply(
        answer="Fully supported. Data is encrypted at rest with AES-256.", compliance="Fully supported"))
    draft = g.answer("Does the product encrypt data at rest?", SOURCES)
    assert client.calls[0]["system"] == COMPLIANCE_SYSTEM
    assert draft.compliance == "Fully supported"


def test_request_shape(settings):
    g, client = gen(settings, lambda s, u: reply())
    g.answer("Describe encryption.", SOURCES)
    call = client.calls[0]
    assert call["model"] == settings.model
    assert call["output_config"]["format"]["type"] == "json_schema"
    assert '<source id="S1"' in call["messages"][0]["content"]


def test_compliance_heuristic():
    assert is_compliance_question("Does the platform support SSO?")
    assert is_compliance_question("Please confirm compliance with ISO 27001.")
    assert not is_compliance_question("Describe your onboarding process.")
    assert not is_compliance_question("What support plans do you offer?")


def test_api_error_is_reported_not_raised(settings):
    request = httpx.Request("POST", "https://api.anthropic.com/v1/messages")
    error = anthropic.BadRequestError("bad", response=httpx.Response(400, request=request), body=None)
    g, _ = gen(settings, lambda s, u: error)
    draft = g.answer("Encryption?", SOURCES)
    assert draft.answer == NO_ANSWER and "API error" in draft.error


def test_malformed_json_is_retried(settings, monkeypatch):
    monkeypatch.setattr("rfp.generation.time.sleep", lambda s: None)
    replies = iter(["not json", reply()])
    g, client = gen(settings, lambda s, u: next(replies))
    assert g.answer("Encryption?", SOURCES).answer.startswith("We encrypt")
    assert len(client.calls) == 2


def test_refusal_is_flagged(settings):
    g, _ = gen(settings, lambda s, u: ("refusal", ""))
    draft = g.answer("Encryption?", SOURCES)
    assert draft.answer == NO_ANSWER and "Refused" in draft.error


def test_answer_many_keeps_order_and_reports_progress(settings):
    def responder(system, user):
        if "boom" in user:
            raise RuntimeError("boom")
        return reply()

    g, _ = gen(settings, responder)
    seen = []
    questions = ["q1", "q2 boom", "q3", "q4", "q5"]
    drafts = g.answer_many(questions, lambda q: SOURCES, progress=lambda d, t: seen.append((d, t)))
    assert [d.question for d in drafts] == questions
    assert drafts[1].answer == NO_ANSWER and drafts[1].error
    assert seen[-1] == (5, 5)
