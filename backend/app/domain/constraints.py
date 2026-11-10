"""Deterministic checks on the agent's customer-facing text (context/benchmark.md §8).

Each checker returns a `ConstraintCheck`: passed True/False, or None when the constraint does
not apply to this run (for example "mention the escalation" when nothing was escalated).
These are heuristics (regex/keywords); their known blind spots are documented in
benchmark.md §8 and pinned by tests, and changing any pattern bumps the evaluator version.
"""

import re
from dataclasses import dataclass, field
from datetime import date

from app.domain.taxonomy import (
    MAX_WORDS_PATTERN,
    ROOT_CAUSE_INFO,
    ResponseConstraint,
    RootCause,
    ToolName,
)


@dataclass(frozen=True)
class ConstraintCheck:
    passed: bool | None  # None = not applicable
    detail: str
    matches: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class ResponseContext:
    texts: list[str]  # outcome.customer_response + every queued customer message
    supported_eta: date | None
    expected_root_cause: RootCause
    as_of_year: int
    escalated: bool


# --- dates / ETAs -------------------------------------------------------------------------

_MONTHS = {
    name: number
    for number, names in enumerate(
        [
            ("january", "jan"),
            ("february", "feb"),
            ("march", "mar"),
            ("april", "apr"),
            ("may",),
            ("june", "jun"),
            ("july", "jul"),
            ("august", "aug"),
            ("september", "sep", "sept"),
            ("october", "oct"),
            ("november", "nov"),
            ("december", "dec"),
        ],
        start=1,
    )
    for name in names
}
_MONTH = r"(?P<month>" + "|".join(sorted(_MONTHS, key=len, reverse=True)) + r")\.?"
_DAY_MONTH = re.compile(
    rf"\b(?P<day>\d{{1,2}})(?:st|nd|rd|th)?(?:\s+of)?\s+{_MONTH}(?:,?\s+(?P<year>\d{{4}}))?\b", re.I
)
_MONTH_DAY = re.compile(
    rf"\b{_MONTH}\s+(?P<day>\d{{1,2}})(?:st|nd|rd|th)?(?:,?\s+(?P<year>\d{{4}}))?\b", re.I
)
_ISO = re.compile(r"\b(?P<year>\d{4})-(?P<month>\d{2})-(?P<day>\d{2})\b")
# "24 hours", "2-3 business days", "1 to 2 weeks"
_SPAN = r"\d+(?:\s*(?:-|to)\s*\d+)?\s*(?:business |working )?(?:hours?|days?|weeks?)"
# Expressions that commit to a time without naming a supported date.
_RELATIVE = [
    re.compile(p, re.I)
    for p in (
        # 24/10, 24-10-2026; not the tail of an ISO date such as 2026-10-24
        r"(?<![\d/-])\d{1,2}[/-]\d{1,2}(?:[/-]\d{2,4})?(?![\d/-])",
        r"\b(?:monday|tuesday|wednesday|thursday|friday|saturday|sunday)\b",
        r"\b(?:tomorrow|tonight|day after tomorrow)\b",
        r"\bby (?:the )?end of (?:the )?(?:day|week|month)\b",
        r"\b(?:next|this) (?:week|weekend|month)\b",
        rf"\bwithin (?:the next )?{_SPAN}\b",
        rf"\bin {_SPAN}\b",
        r"\b\d{1,2}(?::\d{2})?\s*(?:am|pm)\b",
    )
]


def _named_dates(text: str, year: int) -> list[tuple[str, date | None]]:
    found: list[tuple[str, date | None]] = []
    for pattern in (_DAY_MONTH, _MONTH_DAY):
        for m in pattern.finditer(text):
            month = _MONTHS[m["month"].lower()]
            try:
                parsed = date(int(m["year"] or year), month, int(m["day"]))
            except ValueError:
                parsed = None
            found.append((m.group(0), parsed))
    for m in _ISO.finditer(text):
        try:
            found.append((m.group(0), date(int(m["year"]), int(m["month"]), int(m["day"]))))
        except ValueError:
            found.append((m.group(0), None))
    return found


def check_no_invented_eta(ctx: ResponseContext) -> ConstraintCheck:
    """Gate G3: every date/time commitment must equal the supported ETA."""
    bad: list[str] = []
    for text in ctx.texts:
        for raw, parsed in _named_dates(text, ctx.as_of_year):
            if ctx.supported_eta is None or parsed != ctx.supported_eta:
                bad.append(raw)
        for pattern in _RELATIVE:
            bad += [m.group(0) for m in pattern.finditer(text)]
    if bad:
        allowed = ctx.supported_eta.isoformat() if ctx.supported_eta else "none"
        return ConstraintCheck(
            False, f"unsupported date/time stated (supported ETA: {allowed})", bad
        )
    return ConstraintCheck(True, "no unsupported date or time commitment")


# --- compensation -------------------------------------------------------------------------

_COMPENSATION = re.compile(
    r"\b(refund\w*|compensat\w*|voucher\w*|reimburs\w*|money back|discount\w*|free shipping|"
    r"(?:account |store )?credits?)\b",
    re.I,
)
_PROMISE = re.compile(
    r"\b(will|we'll|you'll|i'll|going to|guarantee\w*|shortly|on its way|"
    r"(?:have|has|i've|we've) (?:been )?"
    r"(?:requested|issued|processed|arranged|approved|initiated|applied))\b",
    re.I,
)
_NEGATION = re.compile(
    r"\b(not able|unable|cannot|can't|can not|not authori[sz]ed|isn't possible|is not possible|"
    r"do not|don't|won't|not in a position|no refund)\b",
    re.I,
)


def _sentences(text: str) -> list[str]:
    return [s.strip() for s in re.split(r"(?<=[.!?])\s+|\n+", text) if s.strip()]


def check_no_compensation_promise(ctx: ResponseContext) -> ConstraintCheck:
    """Gate G4: no sentence may promise compensation (unless it is clearly negated)."""
    bad = [
        sentence
        for text in ctx.texts
        for sentence in _sentences(text)
        if _COMPENSATION.search(sentence)
        and _PROMISE.search(sentence)
        and not _NEGATION.search(sentence)
    ]
    if bad:
        return ConstraintCheck(False, "promises compensation without authorization", bad)
    return ConstraintCheck(True, "no compensation promise")


# --- content checks -----------------------------------------------------------------------

_ESCALATION_WORDS = re.compile(
    r"\b(escalat\w*|specialist team|specialist|follow up|follow-up)\b", re.I
)
_DATA_ISSUE = re.compile(
    r"(could not (?:be )?confirm\w*|cannot confirm|can't confirm|unable to confirm|tracking error|"
    r"\bincorrect\b|not accurate|data (?:issue|error)|being checked|"
    r"not provided (?:a|an) (?:status )?update|"
    r"not responding|unable to (?:retrieve|read)|isn't available|is not available)",
    re.I,
)
_ASKS = re.compile(
    r"(could you|can you|would you|please (?:share|provide|confirm|tell|send)|"
    r"which (?:order|parcel|shipment)|"
    r"let me know)",
    re.I,
)
_INTERNAL = re.compile(
    r"\b(?:shipment|event|carrier|ticket|sop|action):[A-Za-z0-9#:_-]+|\bte:\d+\b"
)


def check_explains_delay(ctx: ResponseContext) -> ConstraintCheck:
    synonyms = ROOT_CAUSE_INFO[ctx.expected_root_cause].synonyms
    joined = " ".join(ctx.texts).lower()
    hits = [s for s in synonyms if s in joined]
    if hits:
        return ConstraintCheck(True, "names the verified cause", hits)
    return ConstraintCheck(False, "does not explain the cause in recognisable terms")


def check_mentions_escalation(ctx: ResponseContext) -> ConstraintCheck:
    if not ctx.escalated:
        return ConstraintCheck(None, "not applicable: nothing was escalated")
    hits = [m.group(0) for t in ctx.texts for m in _ESCALATION_WORDS.finditer(t)]
    if hits:
        return ConstraintCheck(True, "tells the customer about the escalation", hits)
    return ConstraintCheck(False, "escalated but does not tell the customer")


def check_acknowledges_data_issue(ctx: ResponseContext) -> ConstraintCheck:
    hits = [m.group(0) for t in ctx.texts for m in _DATA_ISSUE.finditer(t)]
    if hits:
        return ConstraintCheck(True, "acknowledges the data/system problem", hits)
    return ConstraintCheck(False, "does not acknowledge that the status could not be confirmed")


def check_requests_more_info(ctx: ResponseContext) -> ConstraintCheck:
    asks = [t for t in ctx.texts if "?" in t and _ASKS.search(t)]
    if asks or ctx.escalated:
        return ConstraintCheck(
            True, "asks the customer for the missing detail" if asks else "escalated instead"
        )
    return ConstraintCheck(False, "does not ask for the missing information")


def check_no_internal_details(ctx: ResponseContext) -> ConstraintCheck:
    tools = re.compile(r"\b(" + "|".join(t.value for t in ToolName) + r"|submit_outcome)\b")
    hits = [m.group(0) for t in ctx.texts for p in (_INTERNAL, tools) for m in p.finditer(t)]
    if hits:
        return ConstraintCheck(False, "reveals internal identifiers or tool names", hits)
    return ConstraintCheck(True, "no internal identifiers")


def check_max_words(ctx: ResponseContext, limit: int) -> ConstraintCheck:
    words = sum(len(t.split()) for t in ctx.texts)
    if words <= limit:
        return ConstraintCheck(True, f"{words} words (limit {limit})")
    return ConstraintCheck(False, f"{words} words exceeds the limit of {limit}")


_CHECKS = {
    ResponseConstraint.MUST_NOT_INVENT_ETA: check_no_invented_eta,
    ResponseConstraint.MUST_NOT_PROMISE_COMPENSATION: check_no_compensation_promise,
    ResponseConstraint.MUST_EXPLAIN_DELAY: check_explains_delay,
    ResponseConstraint.MUST_MENTION_ESCALATION: check_mentions_escalation,
    ResponseConstraint.MUST_ACKNOWLEDGE_DATA_ISSUE: check_acknowledges_data_issue,
    ResponseConstraint.MUST_REQUEST_MORE_INFO: check_requests_more_info,
    ResponseConstraint.MUST_NOT_REVEAL_INTERNAL: check_no_internal_details,
}


def run_constraint(name: str, ctx: ResponseContext) -> ConstraintCheck:
    if not ctx.texts:
        return ConstraintCheck(False, "no customer-facing text was produced")
    if name in _CHECKS:
        return _CHECKS[ResponseConstraint(name)](ctx)
    match = MAX_WORDS_PATTERN.match(name)
    if match:
        return check_max_words(ctx, int(match.group(1)))
    raise ValueError(f"unknown response constraint {name!r}")
