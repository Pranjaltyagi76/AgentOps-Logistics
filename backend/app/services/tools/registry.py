"""The tool registry: name, description, argument model, kind and handler for every tool."""

from collections.abc import Callable, Iterable
from dataclasses import dataclass
from typing import Any, Literal

from pydantic import BaseModel

from app.domain.taxonomy import POLICY_GATED_TOOLS, READ_TOOLS, ToolName
from app.services.tools import handlers
from app.services.tools.schemas import (
    CarrierArgs,
    CreateSupportTicketArgs,
    RequestEscalationArgs,
    RequestRefundArgs,
    RequestRerouteArgs,
    SearchSopArgs,
    SendCustomerMessageArgs,
    ShipmentArgs,
    TicketArgs,
    ToolOutcome,
)

TOOL_REGISTRY_VERSION = "tools-v1"

Handler = Callable[[handlers.HandlerContext, BaseModel], ToolOutcome]


@dataclass(frozen=True)
class ToolDef:
    name: ToolName
    description: str
    args_model: type[BaseModel]
    handler: Handler

    @property
    def kind(self) -> Literal["read", "mock_write"]:
        return "read" if self.name in READ_TOOLS else "mock_write"

    @property
    def policy_gated(self) -> bool:
        return self.name in POLICY_GATED_TOOLS

    def spec(self) -> dict[str, Any]:
        """JSON-schema tool description handed to the agent (Phase 3)."""
        schema = self.args_model.model_json_schema()
        schema.pop("title", None)
        return {"name": self.name.value, "description": self.description, "parameters": schema}


_TOOLS = [
    ToolDef(
        ToolName.GET_SHIPMENT,
        "Get a shipment record: route, service level, status, promised date, current ETA, carrier.",
        ShipmentArgs,
        handlers.get_shipment,
    ),
    ToolDef(
        ToolName.GET_TRACKING_EVENTS,
        "Get all tracking scans for a shipment in order, each with its evidence_id.",
        ShipmentArgs,
        handlers.get_tracking_events,
    ),
    ToolDef(
        ToolName.GET_CARRIER_STATUS,
        "Get the carrier's current operational status and any service notice.",
        CarrierArgs,
        handlers.get_carrier_status,
    ),
    ToolDef(
        ToolName.GET_TICKET,
        "Get a customer support ticket, including related shipments.",
        TicketArgs,
        handlers.get_ticket,
    ),
    ToolDef(
        ToolName.SEARCH_SOP,
        "Search the support policies (SOPs) you are allowed to use. Returns matching sections.",
        SearchSopArgs,
        handlers.search_sop,
    ),
    ToolDef(
        ToolName.CREATE_SUPPORT_TICKET,
        "Open an internal support ticket, e.g. a data_correction request.",
        CreateSupportTicketArgs,
        handlers.create_support_ticket,
    ),
    ToolDef(
        ToolName.REQUEST_ESCALATION,
        "Escalate the case to the specialist support team with a reason and severity.",
        RequestEscalationArgs,
        handlers.request_escalation,
    ),
    ToolDef(
        ToolName.SEND_CUSTOMER_MESSAGE,
        "Queue a message to the customer (stored in an outbox, not actually sent).",
        SendCustomerMessageArgs,
        handlers.send_customer_message,
    ),
    ToolDef(
        ToolName.REQUEST_REROUTE,
        "Request a change of delivery address. Requires authorization.",
        RequestRerouteArgs,
        handlers.request_reroute,
    ),
    ToolDef(
        ToolName.REQUEST_REFUND,
        "Request a refund for a shipment. Requires authorization.",
        RequestRefundArgs,
        handlers.request_refund,
    ),
]

REGISTRY: dict[str, ToolDef] = {tool.name.value: tool for tool in _TOOLS}


def tool_specs(names: Iterable[str]) -> list[dict[str, Any]]:
    """Specs for the given tools, in registry order."""
    wanted = set(names)
    return [tool.spec() for tool in _TOOLS if tool.name.value in wanted]
