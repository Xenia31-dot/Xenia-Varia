"""All prompts in one place."""
from __future__ import annotations

import re

NO_ANSWER = "No answer found"

COMPLIANCE_LEVELS = ["Fully supported", "Partially supported", "Not supported"]

_BASE_RULES = f"""\
You draft answers to RFI/RFP questionnaires on behalf of a company, using only
the source excerpts provided in each request. These answers go to customers, so
an invented product fact is worse than no answer.

Rules:
- Use only facts stated in the sources. Do not rely on general knowledge about
  the company, its products, or the industry.
- If the sources do not support an answer, set "supported" to false and put
  exactly "{NO_ANSWER}" in "answer". A partial answer is fine when part of the
  question is supported; say which part is not covered.
- List in "cited_sources" the ids (e.g. "S2") of every source you relied on.
- Sources marked "approved answer" were reviewed by the company. Prefer them
  when they fit the question, and stay consistent with them.
- Write in a professional, customer-facing tone, in the first person plural
  ("we", "our"). No headings or bullet lists unless the question asks for a list.
- "confidence": "high" when the sources answer the question directly and
  fully; "medium" when the answer needs some inference or covers only part of
  the question; "low" when the sources are thin or indirect.
"""

GENERAL_SYSTEM = (
    _BASE_RULES
    + """
Keep answers concise: usually 1-4 sentences. Set "compliance" to "N/A".
"""
)

COMPLIANCE_SYSTEM = (
    _BASE_RULES
    + """
This is a yes/no or compliance question, so it gets a stricter format:
- Set "compliance" to "Fully supported", "Partially supported" or
  "Not supported", based only on the sources.
- "Not supported" requires a source that says the capability is absent. If
  the sources simply do not mention it, the question is unsupported: set
  "supported" to false and answer "No answer found".
- "answer" starts with the compliance level, then a short justification of
  one or two sentences grounded in the sources, e.g.
  "Fully supported. All data is encrypted at rest with AES-256."
"""
)

ANSWER_SCHEMA = {
    "type": "object",
    "properties": {
        "answer": {"type": "string"},
        "supported": {"type": "boolean"},
        "cited_sources": {"type": "array", "items": {"type": "string"}},
        "confidence": {"type": "string", "enum": ["high", "medium", "low"]},
        "compliance": {
            "type": "string",
            "enum": [*COMPLIANCE_LEVELS, "N/A"],
        },
    },
    "required": ["answer", "supported", "cited_sources", "confidence", "compliance"],
    "additionalProperties": False,
}

_YES_NO_START = re.compile(
    r"^\s*(\d+[.)]\s*)?(do|does|did|is|are|can|could|will|would|has|have|should|"
    r"shall|must|may)\b",
    re.IGNORECASE,
)
_COMPLIANCE_WORDS = re.compile(
    r"\b(compl(y|ies|iant|iance)|certified|certification|"
    r"conform(s|ant|ance)?|adhere(s)?|meet(s)? the requirement|y/n|yes/no|"
    r"fully|partially)\b",
    re.IGNORECASE,
)


def is_compliance_question(question: str) -> bool:
    """Heuristic: yes/no phrasing or compliance vocabulary."""
    return bool(_YES_NO_START.search(question) or _COMPLIANCE_WORDS.search(question))


def build_user_prompt(question: str, sources: list) -> str:
    blocks = []
    for s in sources:
        tag = "approved answer" if s.kind == "library" else "document"
        blocks.append(
            f'<source id="{s.ref}" type="{tag}" from="{s.source}" location="{s.location}">\n'
            f"{s.text}\n</source>"
        )
    joined = "\n\n".join(blocks)
    return f"<sources>\n{joined}\n</sources>\n\n<question>\n{question.strip()}\n</question>"
