"""Tool implementations. Read tools return scenario data with evidence IDs; mock writes only
record what the agent asked for (nothing leaves the process, PROJECT.md §8)."""

from dataclasses import dataclass, field
from typing import Any

from pydantic import BaseModel

from app.domain.taxonomy import (
    ToolName,
    carrier_evidence_id,
    event_evidence_id,
    shipment_evidence_id,
    ticket_evidence_id,
)
from app.services.sops.service import SopSearcher
from app.services.tools.data_view import ScenarioDataView, as_json
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
    ToolError,
    ToolOutcome,
    ToolResult,
)


@dataclass
class ActionLog:
    """Mock writes made during one run (tickets, escalations, outbox messages, ...)."""

    actions: list[dict[str, Any]] = field(default_factory=list)

    def record(self, kind: str, payload: dict[str, Any]) -> str:
        number = sum(1 for a in self.actions if a["kind"] == kind) + 1
        action_id = f"action:{kind}:{number}"
        self.actions.append({"id": action_id, "kind": kind, "payload": payload})
        return action_id


@dataclass
class HandlerContext:
    data: ScenarioDataView
    sops: SopSearcher
    actions: ActionLog


def _not_found(tool: ToolName, what: str, value: str) -> ToolError:
    return ToolError(tool=tool, code="not_found", message=f"No {what} found with ID {value}")


def _unknown_shipment(ctx: HandlerContext, shipment_id: str | None) -> bool:
    return shipment_id is not None and shipment_id not in ctx.data.shipments


# --- read tools ---------------------------------------------------------------------------


def get_shipment(ctx: HandlerContext, args: BaseModel) -> ToolOutcome:
    assert isinstance(args, ShipmentArgs)
    shipment = ctx.data.shipments.get(args.shipment_id)
    if shipment is None:
        return _not_found(ToolName.GET_SHIPMENT, "shipment", args.shipment_id)
    return ToolResult(
        tool=ToolName.GET_SHIPMENT,
        data=as_json(shipment),
        evidence_ids=[shipment_evidence_id(shipment.shipment_id)],
    )


def get_tracking_events(ctx: HandlerContext, args: BaseModel) -> ToolOutcome:
    assert isinstance(args, ShipmentArgs)
    if args.shipment_id not in ctx.data.shipments:
        return _not_found(ToolName.GET_TRACKING_EVENTS, "shipment", args.shipment_id)
    events = []
    for event in ctx.data.events_for(args.shipment_id):
        events.append(
            {"evidence_id": event_evidence_id(event.shipment_id, event.seq), **as_json(event)}
        )
    return ToolResult(
        tool=ToolName.GET_TRACKING_EVENTS,
        data={"shipment_id": args.shipment_id, "events": events},
        evidence_ids=[e["evidence_id"] for e in events],
    )


def get_carrier_status(ctx: HandlerContext, args: BaseModel) -> ToolOutcome:
    assert isinstance(args, CarrierArgs)
    carrier = ctx.data.carriers.get(args.carrier_id)
    if carrier is None:
        return _not_found(ToolName.GET_CARRIER_STATUS, "carrier", args.carrier_id)
    return ToolResult(
        tool=ToolName.GET_CARRIER_STATUS,
        data=as_json(carrier),
        evidence_ids=[carrier_evidence_id(carrier.carrier_id)],
    )


def get_ticket(ctx: HandlerContext, args: BaseModel) -> ToolOutcome:
    assert isinstance(args, TicketArgs)
    ticket = ctx.data.tickets.get(args.ticket_id)
    if ticket is None:
        return _not_found(ToolName.GET_TICKET, "ticket", args.ticket_id)
    return ToolResult(
        tool=ToolName.GET_TICKET,
        data=as_json(ticket),
        evidence_ids=[ticket_evidence_id(ticket.ticket_id)],
    )


def search_sop(ctx: HandlerContext, args: BaseModel) -> ToolOutcome:
    assert isinstance(args, SearchSopArgs)
    hits = ctx.sops.search(args.query, ctx.data.permitted_documents, args.top_k)
    return ToolResult(
        tool=ToolName.SEARCH_SOP,
        data={
            "query": args.query,
            "results": [
                {
                    "evidence_id": h.evidence_id,
                    "document": h.document_title,
                    "section": h.section_title,
                    "text": h.text,
                    "score": h.score,
                }
                for h in hits
            ],
        },
        evidence_ids=[h.evidence_id for h in hits],
    )


# --- mock writes --------------------------------------------------------------------------


def _record(
    ctx: HandlerContext, tool: ToolName, kind: str, args: BaseModel, **data: Any
) -> ToolOutcome:
    payload = args.model_dump(mode="json")
    if _unknown_shipment(ctx, payload.get("shipment_id")):
        return _not_found(tool, "shipment", payload["shipment_id"])
    action_id = ctx.actions.record(kind, payload)
    return ToolResult(tool=tool, data={"action_id": action_id, **data}, evidence_ids=[action_id])


def create_support_ticket(ctx: HandlerContext, args: BaseModel) -> ToolOutcome:
    assert isinstance(args, CreateSupportTicketArgs)
    return _record(ctx, ToolName.CREATE_SUPPORT_TICKET, "ticket", args, status="created")


def request_escalation(ctx: HandlerContext, args: BaseModel) -> ToolOutcome:
    assert isinstance(args, RequestEscalationArgs)
    return _record(ctx, ToolName.REQUEST_ESCALATION, "escalation", args, status="escalated")


def send_customer_message(ctx: HandlerContext, args: BaseModel) -> ToolOutcome:
    assert isinstance(args, SendCustomerMessageArgs)
    # Outbox only: the message is stored for evaluation, never delivered.
    return _record(ctx, ToolName.SEND_CUSTOMER_MESSAGE, "message", args, status="queued_in_outbox")


def request_reroute(ctx: HandlerContext, args: BaseModel) -> ToolOutcome:
    assert isinstance(args, RequestRerouteArgs)
    # Reached only if policy explicitly authorises reroutes (none do in policy-v1).
    return _record(ctx, ToolName.REQUEST_REROUTE, "reroute", args, status="submitted")


def request_refund(ctx: HandlerContext, args: BaseModel) -> ToolOutcome:
    assert isinstance(args, RequestRefundArgs)
    # Reached only if policy explicitly authorises refunds (none do in policy-v1).
    return _record(ctx, ToolName.REQUEST_REFUND, "refund", args, status="submitted")
