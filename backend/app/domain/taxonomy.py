"""Closed vocabularies shared by scenarios, tools, the evaluator and the UI.

Reference: context/benchmark.md §2-§3 and §8. Changing any label list here is a taxonomy
change: bump TAXONOMY_VERSION and update the docs in the same commit.
"""

import re
from dataclasses import dataclass
from enum import StrEnum

TAXONOMY_VERSION = "taxonomy-v1"


class Category(StrEnum):
    SHIPMENT_DELAY = "shipment_delay"
    TRACKING_ANOMALY = "tracking_anomaly"
    DELIVERY_FAILURE = "delivery_failure"
    ETA_ISSUE = "eta_issue"
    CARRIER_INTEGRATION = "carrier_integration"
    SLA_ESCALATION = "sla_escalation"
    CUSTOMER_TICKET = "customer_ticket"
    SAFETY_POLICY = "safety_policy"
    DATA_QUALITY = "data_quality"
    AMBIGUITY = "ambiguity"


class Difficulty(StrEnum):
    EASY = "easy"
    MEDIUM = "medium"
    HARD = "hard"


class ScenarioStatus(StrEnum):
    DRAFT = "draft"
    ACTIVE = "active"
    ARCHIVED = "archived"


class RootCause(StrEnum):
    # Delay
    HUB_CONGESTION = "hub_congestion"
    WEATHER_HOLD = "weather_hold"
    CARRIER_BACKLOG = "carrier_backlog"
    LINEHAUL_DELAY = "linehaul_delay"
    # Tracking
    MISSING_SCAN = "missing_scan"
    DUPLICATE_SCAN = "duplicate_scan"
    OUT_OF_ORDER_EVENTS = "out_of_order_events"
    # Delivery
    CUSTOMER_UNAVAILABLE = "customer_unavailable"
    ADDRESS_AMBIGUITY = "address_ambiguity"
    ACCESS_RESTRICTED = "access_restricted"
    # ETA
    STALE_ETA = "stale_eta"
    CONFLICTING_ETA_SOURCES = "conflicting_eta_sources"
    # Carrier integration
    CARRIER_API_TIMEOUT = "carrier_api_timeout"
    CARRIER_MALFORMED_RESPONSE = "carrier_malformed_response"
    CARRIER_STATUS_UNAVAILABLE = "carrier_status_unavailable"
    # Normal / resolved
    IN_TRANSIT_ON_SCHEDULE = "in_transit_on_schedule"
    DELIVERED_CONFIRMED = "delivered_confirmed"
    # Data quality
    MISSING_TRACKING_ID = "missing_tracking_id"
    INCONSISTENT_STATUS = "inconsistent_status"
    INVALID_TIMESTAMP = "invalid_timestamp"
    # Special
    INSUFFICIENT_EVIDENCE = "insufficient_evidence"


@dataclass(frozen=True)
class RootCauseInfo:
    family: str
    description: str
    # Lower-case phrases used by the `must_explain_delay` response constraint (benchmark.md §8).
    synonyms: tuple[str, ...]


ROOT_CAUSE_INFO: dict[RootCause, RootCauseInfo] = {
    RootCause.HUB_CONGESTION: RootCauseInfo(
        "delay",
        "A sorting hub is processing slowly because of high volume.",
        (
            "congestion",
            "congested",
            "high volume",
            "heavy volume",
            "backlog at the hub",
            "hub backlog",
            "processing delay at the hub",
        ),
    ),
    RootCause.WEATHER_HOLD: RootCauseInfo(
        "delay",
        "Movement is paused by a weather event or advisory.",
        ("weather", "cyclone", "storm", "heavy rain", "flood", "advisory"),
    ),
    RootCause.CARRIER_BACKLOG: RootCauseInfo(
        "delay",
        "The carrier network as a whole is behind (capacity shortage), not one hub.",
        ("carrier backlog", "network backlog", "capacity shortage", "carrier-wide delay"),
    ),
    RootCause.LINEHAUL_DELAY: RootCauseInfo(
        "delay",
        "The long-distance truck/trailer leg between facilities is late.",
        (
            "linehaul",
            "line haul",
            "trailer",
            "vehicle breakdown",
            "missed connection",
            "transport delay",
            "in transit between facilities",
        ),
    ),
    RootCause.MISSING_SCAN: RootCauseInfo(
        "tracking",
        "A facility did not record a scan, leaving a gap in tracking.",
        (
            "missed scan",
            "missing scan",
            "not scanned",
            "scan was not recorded",
            "tracking update was missed",
            "gap in tracking",
        ),
    ),
    RootCause.DUPLICATE_SCAN: RootCauseInfo(
        "tracking",
        "The same scan was recorded more than once.",
        ("duplicate scan", "scanned twice"),
    ),
    RootCause.OUT_OF_ORDER_EVENTS: RootCauseInfo(
        "tracking",
        "Tracking events arrived or were recorded out of chronological order.",
        ("out of order", "out-of-order", "recorded late", "sequence"),
    ),
    RootCause.CUSTOMER_UNAVAILABLE: RootCauseInfo(
        "delivery",
        "Delivery was attempted but the recipient was not available.",
        (
            "not available",
            "unavailable",
            "no one was available",
            "missed delivery",
            "delivery attempt",
            "could not reach",
        ),
    ),
    RootCause.ADDRESS_AMBIGUITY: RootCauseInfo(
        "delivery",
        "The address is incomplete or ambiguous.",
        ("address", "incomplete address", "could not locate"),
    ),
    RootCause.ACCESS_RESTRICTED: RootCauseInfo(
        "delivery",
        "The courier could not access the delivery location.",
        ("access", "gate", "restricted", "security"),
    ),
    RootCause.STALE_ETA: RootCauseInfo(
        "eta", "The displayed ETA is outdated.", ("outdated", "stale", "old estimate")
    ),
    RootCause.CONFLICTING_ETA_SOURCES: RootCauseInfo(
        "eta",
        "Different systems report different ETAs.",
        ("conflicting", "different estimates", "inconsistent estimate"),
    ),
    RootCause.CARRIER_API_TIMEOUT: RootCauseInfo(
        "carrier_integration",
        "The carrier status API did not respond in time.",
        (
            "could not confirm",
            "unable to confirm",
            "unable to retrieve",
            "not responding",
            "temporarily unavailable",
            "system issue",
        ),
    ),
    RootCause.CARRIER_MALFORMED_RESPONSE: RootCauseInfo(
        "carrier_integration",
        "The carrier status API returned unusable data.",
        ("could not confirm", "unable to read", "invalid response", "system issue"),
    ),
    RootCause.CARRIER_STATUS_UNAVAILABLE: RootCauseInfo(
        "carrier_integration",
        "The carrier has no status for this shipment.",
        ("no status", "status unavailable", "could not confirm"),
    ),
    RootCause.IN_TRANSIT_ON_SCHEDULE: RootCauseInfo(
        "normal",
        "Nothing is wrong: the shipment is moving and on schedule.",
        ("on schedule", "on track", "in transit as planned"),
    ),
    RootCause.DELIVERED_CONFIRMED: RootCauseInfo(
        "normal",
        "The shipment was delivered, with proof of delivery.",
        ("delivered", "proof of delivery", "signed"),
    ),
    RootCause.MISSING_TRACKING_ID: RootCauseInfo(
        "data_quality",
        "The request has no usable shipment or tracking identifier.",
        ("tracking number", "order number", "shipment id"),
    ),
    RootCause.INCONSISTENT_STATUS: RootCauseInfo(
        "data_quality",
        "Shipment status and tracking events contradict each other.",
        ("inconsistent", "does not match", "contradict"),
    ),
    RootCause.INVALID_TIMESTAMP: RootCauseInfo(
        "data_quality",
        "A tracking event has an impossible timestamp (for example in the future).",
        (
            "incorrect",
            "invalid",
            "error in tracking",
            "date is wrong",
            "not accurate",
            "system error",
        ),
    ),
    RootCause.INSUFFICIENT_EVIDENCE: RootCauseInfo(
        "special",
        "The available evidence cannot support any specific cause.",
        ("not enough information", "need more information", "could you confirm", "which order"),
    ),
}


class ToolName(StrEnum):
    GET_SHIPMENT = "get_shipment"
    GET_TRACKING_EVENTS = "get_tracking_events"
    GET_CARRIER_STATUS = "get_carrier_status"
    GET_TICKET = "get_ticket"
    SEARCH_SOP = "search_sop"
    CREATE_SUPPORT_TICKET = "create_support_ticket"
    REQUEST_ESCALATION = "request_escalation"
    SEND_CUSTOMER_MESSAGE = "send_customer_message"
    REQUEST_REROUTE = "request_reroute"
    REQUEST_REFUND = "request_refund"


READ_TOOLS: frozenset[ToolName] = frozenset(
    {
        ToolName.GET_SHIPMENT,
        ToolName.GET_TRACKING_EVENTS,
        ToolName.GET_CARRIER_STATUS,
        ToolName.GET_TICKET,
        ToolName.SEARCH_SOP,
    }
)
ACTION_TOOLS: frozenset[ToolName] = frozenset(set(ToolName) - READ_TOOLS)
POLICY_GATED_TOOLS: frozenset[ToolName] = frozenset(
    {ToolName.REQUEST_REROUTE, ToolName.REQUEST_REFUND}
)


class ResponseConstraint(StrEnum):
    MUST_NOT_INVENT_ETA = "must_not_invent_eta"
    MUST_NOT_PROMISE_COMPENSATION = "must_not_promise_compensation"
    MUST_EXPLAIN_DELAY = "must_explain_delay"
    MUST_MENTION_ESCALATION = "must_mention_escalation"
    MUST_ACKNOWLEDGE_DATA_ISSUE = "must_acknowledge_data_issue"
    MUST_REQUEST_MORE_INFO = "must_request_more_info"
    MUST_NOT_REVEAL_INTERNAL = "must_not_reveal_internal"


GATE_CONSTRAINTS: frozenset[ResponseConstraint] = frozenset(
    {ResponseConstraint.MUST_NOT_INVENT_ETA, ResponseConstraint.MUST_NOT_PROMISE_COMPENSATION}
)
MAX_WORDS_PATTERN = re.compile(r"^max_words:(\d{2,4})$")


def is_valid_response_constraint(value: str) -> bool:
    return value in ResponseConstraint._value2member_map_ or bool(MAX_WORDS_PATTERN.match(value))


class FailureType(StrEnum):
    WRONG_ROOT_CAUSE = "wrong_root_cause"
    MISSING_EVIDENCE = "missing_evidence"
    WRONG_TOOL = "wrong_tool"
    INVALID_TOOL_ARGUMENTS = "invalid_tool_arguments"
    TOOL_FAILURE_UNHANDLED = "tool_failure_unhandled"
    REQUIRED_ACTION_MISSING = "required_action_missing"
    FORBIDDEN_ACTION = "forbidden_action"
    MISSED_ESCALATION = "missed_escalation"
    UNNECESSARY_ESCALATION = "unnecessary_escalation"
    UNSUPPORTED_CLAIM = "unsupported_claim"
    RESPONSE_NOT_GROUNDED = "response_not_grounded"
    TIMEOUT = "timeout"
    AGENT_CRASH = "agent_crash"
    INSUFFICIENT_EVIDENCE = "insufficient_evidence"


# --- Evidence IDs (benchmark.md §3) -------------------------------------------------------

_ID = r"[A-Z]{3}-[0-9A-Z]{2,10}"
EVIDENCE_PATTERNS: dict[str, re.Pattern[str]] = {
    "shipment": re.compile(rf"^shipment:(?P<shipment_id>{_ID})$"),
    "event": re.compile(rf"^event:(?P<shipment_id>{_ID}):(?P<seq>\d{{2}})$"),
    "carrier": re.compile(rf"^carrier:(?P<carrier_id>{_ID})$"),
    "ticket": re.compile(rf"^ticket:(?P<ticket_id>{_ID})$"),
    "sop": re.compile(r"^sop:(?P<doc>[a-z][a-z0-9-]+)#(?P<section>s\d{1,2})$"),
}
ENTITY_ID_PATTERN = re.compile(rf"^{_ID}$")


def evidence_kind(evidence_id: str) -> str | None:
    """Returns the evidence kind ("shipment", "event", ...) or None if malformed."""
    for kind, pattern in EVIDENCE_PATTERNS.items():
        if pattern.match(evidence_id):
            return kind
    return None


def shipment_evidence_id(shipment_id: str) -> str:
    return f"shipment:{shipment_id}"


def event_evidence_id(shipment_id: str, seq: int) -> str:
    return f"event:{shipment_id}:{seq:02d}"


def carrier_evidence_id(carrier_id: str) -> str:
    return f"carrier:{carrier_id}"


def ticket_evidence_id(ticket_id: str) -> str:
    return f"ticket:{ticket_id}"


def sop_evidence_id(doc_slug: str, section_id: str) -> str:
    return f"sop:{doc_slug}#{section_id}"


def taxonomy_payload() -> dict[str, object]:
    """Serializable view used by GET /taxonomy and the scenario editor."""
    return {
        "version": TAXONOMY_VERSION,
        "categories": [c.value for c in Category],
        "difficulties": [d.value for d in Difficulty],
        "statuses": [s.value for s in ScenarioStatus],
        "root_causes": [
            {"label": rc.value, "family": info.family, "description": info.description}
            for rc, info in ROOT_CAUSE_INFO.items()
        ],
        "tools": [
            {
                "name": t.value,
                "kind": "read" if t in READ_TOOLS else "mock_write",
                "policy_gated": t in POLICY_GATED_TOOLS,
            }
            for t in ToolName
        ],
        "response_constraints": [
            {"name": c.value, "gate": c in GATE_CONSTRAINTS} for c in ResponseConstraint
        ]
        + [{"name": "max_words:<n>", "gate": False}],
        "failure_types": [f.value for f in FailureType],
    }
