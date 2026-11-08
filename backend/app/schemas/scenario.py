"""Scenario file / import schema (`ScenarioSpec`) and its semantic validation.

Structure is enforced by Pydantic; cross-field rules (evidence IDs exist, tool lists are
consistent, ...) are enforced by `semantic_issues()`. Always validate through
`validate_scenario()` so both layers run. Reference: context/benchmark.md §3-§5.
"""

from datetime import date, datetime
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

from app.domain.sop_catalog import SopCatalog
from app.domain.taxonomy import (
    ACTION_TOOLS,
    ENTITY_ID_PATTERN,
    EVIDENCE_PATTERNS,
    Category,
    Difficulty,
    RootCause,
    ToolName,
    carrier_evidence_id,
    event_evidence_id,
    evidence_kind,
    is_valid_response_constraint,
    shipment_evidence_id,
    ticket_evidence_id,
)

EntityId = Annotated[str, Field(pattern=ENTITY_ID_PATTERN.pattern)]
AwareDatetime = Annotated[datetime, Field(description="ISO 8601 with timezone offset")]


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


# --- Mock data records ------------------------------------------------------------------


class Shipment(StrictModel):
    shipment_id: EntityId
    customer_id: EntityId
    carrier_id: EntityId | None = None
    origin_city: str
    destination_city: str
    service_level: Literal["standard", "express"]
    status: Literal[
        "created", "in_transit", "out_for_delivery", "delivered", "delivery_exception", "on_hold"
    ]
    promised_delivery_date: date
    current_eta: date | None = None
    eta_status: Literal["confirmed", "estimated", "recalculating", "unavailable"] = "estimated"
    recipient_name: str | None = Field(default=None, description="Fictional; redacted in display")
    delivery_attempts: int = Field(default=0, ge=0, le=10)
    next_attempt_date: date | None = None
    created_at: AwareDatetime

    @field_validator("created_at")
    @classmethod
    def _aware(cls, value: datetime) -> datetime:
        return _require_tz(value)


class TrackingEvent(StrictModel):
    shipment_id: EntityId
    seq: int = Field(ge=1, le=99)
    timestamp: AwareDatetime
    location: str
    event_code: str = Field(pattern=r"^[A-Z][A-Z_]{2,40}$")
    description: str

    @field_validator("timestamp")
    @classmethod
    def _aware(cls, value: datetime) -> datetime:
        return _require_tz(value)


class CarrierStatus(StrictModel):
    carrier_id: EntityId
    name: str
    status: Literal["operational", "degraded", "outage"]
    notice: str | None = None
    updated_at: AwareDatetime

    @field_validator("updated_at")
    @classmethod
    def _aware(cls, value: datetime) -> datetime:
        return _require_tz(value)


class Ticket(StrictModel):
    ticket_id: EntityId
    customer_id: EntityId
    shipment_id: EntityId | None = None
    related_shipment_ids: list[EntityId] = Field(default_factory=list)
    status: Literal["open", "pending", "resolved"]
    channel: Literal["email", "chat", "phone", "app"]
    opened_at: AwareDatetime
    subject: str
    last_customer_message: str | None = None

    @field_validator("opened_at")
    @classmethod
    def _aware(cls, value: datetime) -> datetime:
        return _require_tz(value)


class MockData(StrictModel):
    shipments: list[Shipment] = Field(default_factory=list)
    tracking_events: list[TrackingEvent] = Field(default_factory=list)
    carrier_status: list[CarrierStatus] = Field(default_factory=list)
    tickets: list[Ticket] = Field(default_factory=list)

    def evidence_ids(self) -> set[str]:
        """Every evidence ID a tool could return from this data."""
        ids = {shipment_evidence_id(s.shipment_id) for s in self.shipments}
        ids |= {event_evidence_id(e.shipment_id, e.seq) for e in self.tracking_events}
        ids |= {carrier_evidence_id(c.carrier_id) for c in self.carrier_status}
        ids |= {ticket_evidence_id(t.ticket_id) for t in self.tickets}
        return ids


# --- Test design ------------------------------------------------------------------------


class FaultInjection(StrictModel):
    tool: ToolName
    error: Literal["timeout", "malformed_response", "unavailable"]
    latency_ms: int = Field(default=0, ge=0, le=30_000)
    # Which calls (1-based) fail; "all" = every call.
    calls: list[int] | Literal["all"] = "all"


class GroundTruth(StrictModel):
    root_cause: RootCause
    required_evidence: list[str] = Field(default_factory=list)
    required_tools: list[ToolName] = Field(default_factory=list)
    required_actions: list[ToolName] = Field(default_factory=list)
    forbidden_actions: list[ToolName] = Field(default_factory=list)
    expected_escalation: bool
    supported_eta: date | None = None
    sequence_constraints: list[tuple[ToolName, ToolName]] = Field(default_factory=list)
    response_constraints: list[str] = Field(default_factory=list)


class Weights(StrictModel):
    root_cause: int = Field(default=25, ge=0, le=100)
    evidence: int = Field(default=20, ge=0, le=100)
    tool_correctness: int = Field(default=20, ge=0, le=100)
    policy: int = Field(default=20, ge=0, le=100)
    response_quality: int = Field(default=15, ge=0, le=100)

    def total(self) -> int:
        return (
            self.root_cause
            + self.evidence
            + self.tool_correctness
            + self.policy
            + self.response_quality
        )


class Evaluation(StrictModel):
    weights: Weights = Field(default_factory=Weights)
    pass_threshold: int = Field(default=70, ge=0, le=100)
    rubric: str | None = None


class ScenarioSpec(StrictModel):
    scenario_id: str = Field(pattern=r"^[a-z][a-z0-9_]*_\d{3}$", max_length=80)
    version: int = Field(ge=1)
    title: str = Field(min_length=3, max_length=160)
    description: str = Field(min_length=3, max_length=2000)
    category: Category
    difficulty: Difficulty
    as_of: AwareDatetime = Field(description="Simulated 'now' for this scenario")
    customer_message: str = Field(min_length=1, max_length=2000)
    visible_context: dict[str, str] = Field(default_factory=dict)
    mock_data: MockData = Field(default_factory=MockData)
    permitted_documents: list[str] = Field(default_factory=list)
    available_tools: list[ToolName] = Field(min_length=1)
    fault_injection: list[FaultInjection] = Field(default_factory=list)
    ground_truth: GroundTruth
    evaluation: Evaluation = Field(default_factory=Evaluation)
    tags: list[Annotated[str, Field(pattern=r"^[a-z0-9][a-z0-9_-]{0,39}$")]] = Field(
        default_factory=list
    )
    author_note: str | None = Field(default=None, max_length=2000)

    @field_validator("as_of")
    @classmethod
    def _aware(cls, value: datetime) -> datetime:
        return _require_tz(value)

    def visible_view(self) -> dict[str, Any]:
        """Everything except hidden test design (ground truth, evaluation, faults, notes)."""
        return self.model_dump(
            mode="json",
            exclude={"ground_truth", "evaluation", "fault_injection", "author_note"},
        )


def _require_tz(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("timestamp must include a timezone offset, e.g. +05:30")
    return value


# --- Validation ---------------------------------------------------------------------------


class ValidationIssue(BaseModel):
    loc: str
    msg: str


class ValidationReport(BaseModel):
    valid: bool
    errors: list[ValidationIssue] = Field(default_factory=list)
    warnings: list[ValidationIssue] = Field(default_factory=list)


def _duplicates(values: list[Any]) -> set[Any]:
    seen: set[Any] = set()
    return {v for v in values if v in seen or seen.add(v)}  # type: ignore[func-returns-value]


def semantic_issues(
    spec: ScenarioSpec, catalog: SopCatalog
) -> tuple[list[ValidationIssue], list[ValidationIssue]]:
    """Cross-field rules. Returns (errors, warnings)."""
    errors: list[ValidationIssue] = []
    warnings: list[ValidationIssue] = []

    def err(loc: str, msg: str) -> None:
        errors.append(ValidationIssue(loc=loc, msg=msg))

    def warn(loc: str, msg: str) -> None:
        warnings.append(ValidationIssue(loc=loc, msg=msg))

    data = spec.mock_data
    gt = spec.ground_truth
    tools = set(spec.available_tools)

    # Unique records
    for dup in _duplicates([s.shipment_id for s in data.shipments]):
        err("mock_data.shipments", f"duplicate shipment_id {dup}")
    for dup in _duplicates([(e.shipment_id, e.seq) for e in data.tracking_events]):
        err("mock_data.tracking_events", f"duplicate event {dup[0]} seq {dup[1]}")
    for dup in _duplicates([c.carrier_id for c in data.carrier_status]):
        err("mock_data.carrier_status", f"duplicate carrier_id {dup}")
    for dup in _duplicates([t.ticket_id for t in data.tickets]):
        err("mock_data.tickets", f"duplicate ticket_id {dup}")
    for dup in _duplicates(list(spec.available_tools)):
        err("available_tools", f"duplicate tool {dup}")

    # Referential integrity inside mock data
    shipment_ids = {s.shipment_id for s in data.shipments}
    for i, event in enumerate(data.tracking_events):
        if event.shipment_id not in shipment_ids:
            err(f"mock_data.tracking_events[{i}]", f"unknown shipment_id {event.shipment_id}")
        if event.timestamp > spec.as_of:
            warn(f"mock_data.tracking_events[{i}]", "timestamp is after as_of (future-dated)")
    for i, ticket in enumerate(data.tickets):
        for sid in [ticket.shipment_id, *ticket.related_shipment_ids]:
            if sid is not None and sid not in shipment_ids:
                err(f"mock_data.tickets[{i}]", f"unknown shipment_id {sid}")
    shipment_ref = spec.visible_context.get("shipment_id")
    if shipment_ref is not None and shipment_ref not in shipment_ids:
        err("visible_context.shipment_id", f"{shipment_ref} is not in mock_data.shipments")

    # SOP documents
    for i, slug in enumerate(spec.permitted_documents):
        if catalog.get(slug) is None:
            err(f"permitted_documents[{i}]", f"unknown SOP document '{slug}'")
    if spec.permitted_documents and ToolName.SEARCH_SOP not in tools:
        err("available_tools", "permitted_documents is set but search_sop is not available")

    # Evidence IDs
    record_ids = data.evidence_ids()
    for dup in _duplicates(gt.required_evidence):
        err("ground_truth.required_evidence", f"duplicate evidence ID {dup}")
    for i, evidence_id in enumerate(gt.required_evidence):
        loc = f"ground_truth.required_evidence[{i}]"
        kind = evidence_kind(evidence_id)
        if kind is None:
            err(loc, f"malformed evidence ID '{evidence_id}' (see context/benchmark.md §3)")
        elif kind == "sop":
            match = EVIDENCE_PATTERNS["sop"].match(evidence_id)
            assert match is not None
            doc = catalog.get(match["doc"])
            if match["doc"] not in spec.permitted_documents:
                err(loc, f"SOP '{match['doc']}' is not in permitted_documents")
            elif doc is None or match["section"] not in doc.section_ids:
                err(loc, f"SOP section '{evidence_id}' does not exist in the SOP catalog")
        elif evidence_id not in record_ids:
            err(loc, f"'{evidence_id}' does not match any record in mock_data")

    # Tool lists
    for name, listed in (
        ("required_tools", gt.required_tools),
        ("required_actions", gt.required_actions),
        ("forbidden_actions", gt.forbidden_actions),
    ):
        for tool in listed:
            if tool not in tools:
                err(f"ground_truth.{name}", f"'{tool}' must also be listed in available_tools")
    for tool in gt.required_actions:
        if tool not in ACTION_TOOLS:
            err(
                "ground_truth.required_actions",
                f"'{tool}' is a read tool; list it in required_tools",
            )
    for tool in gt.forbidden_actions:
        if tool not in ACTION_TOOLS:
            err(
                "ground_truth.forbidden_actions", f"'{tool}' is a read tool and cannot be forbidden"
            )
    for tool in set(gt.required_actions) & set(gt.forbidden_actions):
        err("ground_truth", f"'{tool}' is both required and forbidden")
    if ToolName.REQUEST_ESCALATION in gt.forbidden_actions:
        err("ground_truth.forbidden_actions", "request_escalation cannot be forbidden")
    if gt.expected_escalation and ToolName.REQUEST_ESCALATION not in tools:
        err(
            "available_tools", "expected_escalation is true but request_escalation is not available"
        )
    for i, (first, then) in enumerate(gt.sequence_constraints):
        if first == then:
            err(f"ground_truth.sequence_constraints[{i}]", "a tool cannot precede itself")
        for tool in (first, then):
            if tool not in tools:
                err(f"ground_truth.sequence_constraints[{i}]", f"'{tool}' is not available")

    # Response constraints
    for dup in _duplicates(gt.response_constraints):
        err("ground_truth.response_constraints", f"duplicate constraint {dup}")
    for i, constraint in enumerate(gt.response_constraints):
        if not is_valid_response_constraint(constraint):
            err(f"ground_truth.response_constraints[{i}]", f"unknown constraint '{constraint}'")
    if gt.supported_eta is None and "must_not_invent_eta" not in gt.response_constraints:
        warn(
            "ground_truth.response_constraints",
            "no supported_eta but must_not_invent_eta is absent",
        )

    # Faults
    for i, fault in enumerate(spec.fault_injection):
        if fault.tool not in tools:
            err(f"fault_injection[{i}]", f"'{fault.tool}' is not in available_tools")

    # Evaluation
    if spec.evaluation.weights.total() != 100:
        err(
            "evaluation.weights", f"weights must sum to 100 (got {spec.evaluation.weights.total()})"
        )

    return errors, warnings


def validate_scenario(
    data: Any, catalog: SopCatalog
) -> tuple[ScenarioSpec | None, ValidationReport]:
    """Validates raw scenario JSON. Returns the parsed spec only when it is fully valid."""
    try:
        spec = ScenarioSpec.model_validate(data)
    except ValidationError as exc:
        issues = [
            ValidationIssue(
                loc=".".join(str(part) for part in err["loc"]) or "(root)", msg=err["msg"]
            )
            for err in exc.errors()
        ]
        return None, ValidationReport(valid=False, errors=issues)
    errors, warnings = semantic_issues(spec, catalog)
    report = ValidationReport(valid=not errors, errors=errors, warnings=warnings)
    return (spec if not errors else None), report
