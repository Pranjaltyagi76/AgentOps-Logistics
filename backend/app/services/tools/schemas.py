"""Tool argument models (what an agent may send) and typed results (what it gets back).

Argument models forbid unknown fields; descriptions are shown to the agent as part of the tool
spec. Results are plain JSON-serialisable models so they can be stored in traces (Phase 4).
"""

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from app.domain.taxonomy import ENTITY_ID_PATTERN, ToolName

EntityId = Field(pattern=ENTITY_ID_PATTERN.pattern, description="Identifier such as SHP-1042")


class ToolArgs(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class ShipmentArgs(ToolArgs):
    shipment_id: str = EntityId


class CarrierArgs(ToolArgs):
    carrier_id: str = Field(
        pattern=ENTITY_ID_PATTERN.pattern, description="Carrier ID such as CAR-SWIFT"
    )


class TicketArgs(ToolArgs):
    ticket_id: str = Field(
        pattern=ENTITY_ID_PATTERN.pattern, description="Ticket ID such as TKT-0720"
    )


class SearchSopArgs(ToolArgs):
    query: str = Field(min_length=3, max_length=200, description="What to look up in the SOPs")
    top_k: int = Field(default=3, ge=1, le=5, description="Number of sections to return")


class CreateSupportTicketArgs(ToolArgs):
    category: Literal["data_correction", "delivery_issue", "customer_followup", "other"]
    summary: str = Field(min_length=10, max_length=1000)
    shipment_id: str | None = Field(default=None, pattern=ENTITY_ID_PATTERN.pattern)


class RequestEscalationArgs(ToolArgs):
    reason: str = Field(
        min_length=10, max_length=1000, description="Factual reason citing evidence"
    )
    severity: Literal["low", "medium", "high", "critical"]
    shipment_id: str | None = Field(default=None, pattern=ENTITY_ID_PATTERN.pattern)


class SendCustomerMessageArgs(ToolArgs):
    message: str = Field(min_length=1, max_length=2000)
    channel: Literal["chat", "email", "sms", "app"] = "chat"


class RequestRerouteArgs(ToolArgs):
    shipment_id: str = EntityId
    new_address: str = Field(min_length=5, max_length=300)
    reason: str = Field(min_length=5, max_length=500)


class RequestRefundArgs(ToolArgs):
    shipment_id: str = EntityId
    amount_inr: float = Field(gt=0, le=1_000_000)
    reason: str = Field(min_length=5, max_length=500)


ToolErrorCode = Literal[
    "unknown_tool",
    "tool_not_permitted",
    "tool_budget_exceeded",
    "invalid_arguments",
    "policy_denied",
    "not_found",
    "timeout",
    "malformed_response",
    "unavailable",
]


class ToolResult(BaseModel):
    ok: Literal[True] = True
    tool: ToolName
    data: Any
    evidence_ids: list[str] = Field(default_factory=list)


class ToolError(BaseModel):
    ok: Literal[False] = False
    tool: str
    code: ToolErrorCode
    message: str
    retryable: bool = False
    details: dict[str, Any] = Field(default_factory=dict)


ToolOutcome = ToolResult | ToolError
