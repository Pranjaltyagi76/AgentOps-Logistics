"""Deterministic, no-LLM agents (decision D-05).

They read only the agent input and tool observations, exactly like an LLM agent would, and
are labelled "rule-based baseline" everywhere: they validate the platform and give a free
demo; they are not evidence of AI capability.

Profiles:
- "v1":        follows the SOPs: gathers evidence, retries a timed-out carrier call once,
               spots invalid timestamps, searches the relevant SOP, escalates per policy.
- "v2_flawed": the same agent with realistic bugs (skips SOP search, ignores tool errors,
               trusts impossible timestamps, quotes the promised date as an ETA, guesses
               between orders, tries to refund/reroute when asked). Used to demonstrate a
               reproducible regression.
"""

import re
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any, Literal

from app.domain.taxonomy import RootCause, ToolName
from app.services.agent_graph.deciders import AgentState, Observation, call
from app.services.agent_graph.schemas import SUBMIT_OUTCOME, ModelTurn, ToolCallRequest

Profile = Literal["v1", "v2_flawed"]
PROFILES: tuple[Profile, ...] = ("v1", "v2_flawed")

_REFUND = re.compile(r"\b(refund|compensat\w*|money back|reimburs\w*)", re.IGNORECASE)
_REROUTE = re.compile(
    r"\b(send it to|deliver it to|redirect|change (the )?address|to my office)", re.IGNORECASE
)
_CARRIER_FAILURE_CAUSE = {
    "timeout": RootCause.CARRIER_API_TIMEOUT,
    "unavailable": RootCause.CARRIER_STATUS_UNAVAILABLE,
    "malformed_response": RootCause.CARRIER_MALFORMED_RESPONSE,
}
_SOP_QUERIES = {
    "data_issue": "tracking event dated in the future invalid timestamp",
    "carrier_failure": "carrier API timeout status cannot be confirmed",
    "refund": "customer requests refund compensation authorization",
    "sla_breach": "SLA thresholds by service level breach",
    "failed_delivery": "redelivery options after failed delivery attempt",
    "delay": "ETA statements delivery date estimate not available",
}


def _parse_dt(value: str) -> datetime:
    return datetime.fromisoformat(value)


def _fmt_date(value: str | date) -> str:
    day = date.fromisoformat(value) if isinstance(value, str) else value
    return f"{day.day} {day.strftime('%B %Y')}"


@dataclass
class Knowledge:
    """What the agent has learned so far, derived only from its input and tool observations."""

    context: dict[str, str]
    message: str
    now: datetime
    tools: set[str]
    observations: list[Observation]

    @classmethod
    def from_state(cls, state: AgentState) -> "Knowledge":
        agent_input = state["input"]
        return cls(
            context=dict(agent_input["visible_context"]),
            message=agent_input["customer_message"],
            now=_parse_dt(agent_input["now"]),
            tools={t["name"] for t in agent_input["tools"]},
            observations=list(state["observations"]),
        )

    def calls_to(self, tool: str) -> list[Observation]:
        return [o for o in self.observations if o["tool"] == tool]

    def first_ok(self, tool: str) -> Observation | None:
        return next((o for o in self.calls_to(tool) if o["ok"]), None)

    def can(self, tool: str) -> bool:
        return tool in self.tools


@dataclass
class Diagnosis:
    root_cause: RootCause
    situation: str
    evidence: list[str] = field(default_factory=list)
    location: str | None = None
    eta: str | None = None
    escalate: bool = False
    escalation_reason: str = ""
    severity: str = "high"
    data_ticket: str | None = None
    ask_which_order: bool = False
    refund_requested: bool = False
    reroute_requested: bool = False
    carrier_failed: bool = False
    hours_since_scan: float | None = None


class RuleBasedDecider:
    def __init__(self, profile: Profile = "v1") -> None:
        if profile not in PROFILES:
            raise ValueError(f"unknown rule-based profile {profile!r}")
        self.profile = profile
        self.name = f"rule_based:{profile}"

    @property
    def flawed(self) -> bool:
        return self.profile == "v2_flawed"

    # --- decide -------------------------------------------------------------------------

    def decide(self, state: AgentState) -> ModelTurn:
        kb = Knowledge.from_state(state)
        next_call = self._next_lookup(kb)
        if next_call is None:
            diagnosis = self._diagnose(kb)
            next_call = self._next_action(kb, diagnosis)
            if next_call is None:
                outcome = self._outcome(kb, diagnosis)
                return ModelTurn(tool_calls=[call(SUBMIT_OUTCOME, outcome)])
        return ModelTurn(tool_calls=[next_call])

    def _ticket(self, kb: Knowledge) -> dict[str, Any] | None:
        obs = kb.first_ok(ToolName.GET_TICKET)
        return obs["data"] if obs else None

    def _shipment_id(self, kb: Knowledge) -> str | None:
        if kb.context.get("shipment_id"):
            return kb.context["shipment_id"]
        ticket = self._ticket(kb)
        if ticket is None:
            return None
        if ticket.get("shipment_id"):
            return ticket["shipment_id"]
        related = ticket.get("related_shipment_ids") or []
        if len(related) == 1 or (related and self.flawed):  # v2 guesses the first order
            return related[0]
        return None

    def _next_lookup(self, kb: Knowledge) -> ToolCallRequest | None:
        ticket_id = kb.context.get("ticket_id")
        if ticket_id and kb.can(ToolName.GET_TICKET) and not kb.calls_to(ToolName.GET_TICKET):
            return call(ToolName.GET_TICKET, {"ticket_id": ticket_id})
        shipment_id = self._shipment_id(kb)
        if shipment_id is None:
            return None
        for tool in (ToolName.GET_SHIPMENT, ToolName.GET_TRACKING_EVENTS):
            if kb.can(tool) and not kb.calls_to(tool):
                return call(tool, {"shipment_id": shipment_id})
        shipment = kb.first_ok(ToolName.GET_SHIPMENT)
        carrier_id = shipment["data"].get("carrier_id") if shipment else None
        if carrier_id and kb.can(ToolName.GET_CARRIER_STATUS):
            attempts = kb.calls_to(ToolName.GET_CARRIER_STATUS)
            if not attempts:
                return call(ToolName.GET_CARRIER_STATUS, {"carrier_id": carrier_id}, "carrier-1")
            last_error = attempts[-1]["error"] or {}
            # SOP carrier-integration s2: retry a timed-out call once (v2 never retries).
            if not self.flawed and len(attempts) == 1 and last_error.get("retryable"):
                return call(ToolName.GET_CARRIER_STATUS, {"carrier_id": carrier_id}, "carrier-2")
        return None

    # --- diagnose -------------------------------------------------------------------------

    def _diagnose(self, kb: Knowledge) -> Diagnosis:
        refund = bool(_REFUND.search(kb.message))
        reroute = bool(_REROUTE.search(kb.message))
        shipment_obs = kb.first_ok(ToolName.GET_SHIPMENT)
        if shipment_obs is None:
            ticket = self._ticket(kb)
            evidence = [f"ticket:{ticket['ticket_id']}"] if ticket else []
            return Diagnosis(
                RootCause.INSUFFICIENT_EVIDENCE,
                "ambiguous",
                evidence=evidence,
                ask_which_order=True,
                refund_requested=refund,
                reroute_requested=reroute,
            )

        shipment = shipment_obs["data"]
        events_obs = kb.first_ok(ToolName.GET_TRACKING_EVENTS)
        events = list(events_obs["data"]["events"]) if events_obs else []
        valid, invalid = events, []
        if not self.flawed:  # v2 trusts every event, even impossible ones
            invalid = [
                e
                for e in events
                if _parse_dt(e["timestamp"]) > kb.now
                or (e["event_code"] == "DELIVERED" and shipment["status"] != "delivered")
            ]
            valid = [e for e in events if e not in invalid]
        last = valid[-1] if valid else None
        hours = (kb.now - _parse_dt(last["timestamp"])).total_seconds() / 3600 if last else None

        carrier_calls = kb.calls_to(ToolName.GET_CARRIER_STATUS)
        carrier_ok = kb.first_ok(ToolName.GET_CARRIER_STATUS)
        carrier_error = None
        if carrier_calls and carrier_ok is None and not self.flawed:
            carrier_error = (carrier_calls[-1]["error"] or {}).get("code")

        d = Diagnosis(
            RootCause.IN_TRANSIT_ON_SCHEDULE,
            "delay",
            location=last["location"] if last else None,
            refund_requested=refund,
            reroute_requested=reroute,
            hours_since_scan=hours,
        )
        d.evidence.append(f"shipment:{shipment['shipment_id']}")

        if invalid:
            bad = invalid[-1]
            d.root_cause, d.situation = RootCause.INVALID_TIMESTAMP, "data_issue"
            d.evidence += [bad["evidence_id"]] + ([last["evidence_id"]] if last else [])
            d.data_ticket = (
                f"Tracking event {bad['event_code']} for {shipment['shipment_id']} is dated "
                f"{bad['timestamp']}, after the current time and inconsistent with the shipment "
                "status. Please correct the tracking record."
            )
        elif carrier_error in _CARRIER_FAILURE_CAUSE:
            d.root_cause, d.situation = _CARRIER_FAILURE_CAUSE[carrier_error], "carrier_failure"
            d.carrier_failed = True
            d.evidence += [last["evidence_id"]] if last else []
            if hours is not None and hours > 24:
                d.escalate, d.severity = True, "medium"
                d.escalation_reason = (
                    f"Carrier status could not be confirmed ({carrier_error}) and there has been "
                    f"no new scan for {hours:.0f} hours"
                )
        else:
            self._diagnose_from_events(d, valid, carrier_ok)

        self._apply_sla(kb, d, shipment)
        if refund and not self.flawed:
            d.situation = "refund" if d.situation in ("delay", "sla_breach") else d.situation
            if not d.escalate:
                d.escalate, d.severity = True, "high"
                d.escalation_reason = "Customer requests a refund or compensation"
        d.eta = self._eta(shipment, d)
        return d

    def _diagnose_from_events(
        self, d: Diagnosis, events: list[dict[str, Any]], carrier: Observation | None
    ) -> None:
        notice = ((carrier or {}).get("data") or {}).get("notice") or ""
        for index in range(len(events) - 1, -1, -1):
            event = events[index]
            code, text = event["event_code"], event["description"].lower()
            cause: RootCause | None = None
            situation = "delay"
            cited = [event["evidence_id"]]
            if code == "HUB_DELAY":
                network = "network" in notice.lower()
                cause = RootCause.CARRIER_BACKLOG if network else RootCause.HUB_CONGESTION
            elif code == "WEATHER_HOLD":
                cause = RootCause.WEATHER_HOLD
            elif code == "LINEHAUL_DELAYED":
                cause = RootCause.LINEHAUL_DELAY
            elif code == "DELIVERY_ATTEMPT_FAILED":
                situation = "failed_delivery"
                if "address" in text:
                    cause = RootCause.ADDRESS_AMBIGUITY
                elif "access" in text:
                    cause = RootCause.ACCESS_RESTRICTED
                else:
                    cause = RootCause.CUSTOMER_UNAVAILABLE
            elif "scan" in text and "not recorded" in text:
                cause = RootCause.MISSING_SCAN
                cited = [events[index - 1]["evidence_id"], event["evidence_id"]] if index else cited
            elif code == "DELIVERED":
                cause = RootCause.DELIVERED_CONFIRMED
            if cause is not None:
                d.root_cause, d.situation = cause, situation
                d.evidence += cited
                break
        else:
            if events:
                d.evidence.append(events[-1]["evidence_id"])
        if carrier and carrier.get("data", {}).get("status") != "operational" and not self.flawed:
            d.evidence += carrier["evidence_ids"]

    def _apply_sla(self, kb: Knowledge, d: Diagnosis, shipment: dict[str, Any]) -> None:
        if shipment["status"] == "delivered" or d.root_cause == RootCause.DELIVERED_CONFIRMED:
            return
        days_late = (kb.now.date() - date.fromisoformat(shipment["promised_delivery_date"])).days
        express = shipment["service_level"] == "express"
        breached = days_late >= 1 if express else days_late >= 2
        if self.flawed:
            breached = express and days_late >= 1  # v2 forgets the standard-service rule
        if breached and not d.escalate:
            d.escalate, d.severity = True, "high"
            d.escalation_reason = (
                f"SLA breached: {shipment['service_level']} shipment promised for "
                f"{shipment['promised_delivery_date']} is {days_late} day(s) late"
            )
            if d.situation == "delay":
                d.situation = "sla_breach"

    def _eta(self, shipment: dict[str, Any], d: Diagnosis) -> str | None:
        if d.root_cause == RootCause.CUSTOMER_UNAVAILABLE and shipment.get("next_attempt_date"):
            return shipment["next_attempt_date"]
        if self.flawed:  # v2 falls back to the original promised date
            return shipment.get("current_eta") or shipment.get("promised_delivery_date")
        if d.situation in ("data_issue", "carrier_failure"):
            return None
        if shipment.get("eta_status") in ("confirmed", "estimated"):
            return shipment.get("current_eta")
        return None

    # --- act --------------------------------------------------------------------------------

    def _next_action(self, kb: Knowledge, d: Diagnosis) -> ToolCallRequest | None:
        if (
            not self.flawed
            and not d.ask_which_order
            and kb.can(ToolName.SEARCH_SOP)
            and not kb.calls_to(ToolName.SEARCH_SOP)
        ):
            return call(ToolName.SEARCH_SOP, {"query": _SOP_QUERIES[d.situation], "top_k": 3})
        shipment_id = self._shipment_id(kb)

        def todo(tool: ToolName, wanted: bool) -> bool:
            return wanted and kb.can(tool) and not kb.calls_to(tool)

        if todo(ToolName.CREATE_SUPPORT_TICKET, d.data_ticket is not None):
            args = {"category": "data_correction", "summary": d.data_ticket}
            return call(ToolName.CREATE_SUPPORT_TICKET, {**args, "shipment_id": shipment_id})
        # v2's flaw: it acts on refund/reroute requests itself (policy blocks and records it).
        if todo(ToolName.REQUEST_REFUND, self.flawed and d.refund_requested and bool(shipment_id)):
            args = {"shipment_id": shipment_id, "amount_inr": 150, "reason": "Late delivery"}
            return call(ToolName.REQUEST_REFUND, args)
        if todo(
            ToolName.REQUEST_REROUTE, self.flawed and d.reroute_requested and bool(shipment_id)
        ):
            args = {
                "shipment_id": shipment_id,
                "new_address": "Customer office address",
                "reason": "Customer asked to deliver to the office",
            }
            return call(ToolName.REQUEST_REROUTE, args)
        if todo(ToolName.REQUEST_ESCALATION, d.escalate):
            reason = d.escalation_reason
            if d.location:
                reason += f"; last valid scan at {d.location}"
            args = {"reason": reason + ".", "severity": d.severity}
            return call(ToolName.REQUEST_ESCALATION, {**args, "shipment_id": shipment_id})
        return None

    # --- respond ----------------------------------------------------------------------------

    def _outcome(self, kb: Knowledge, d: Diagnosis) -> dict[str, Any]:
        escalated = any(o["ok"] for o in kb.calls_to(ToolName.REQUEST_ESCALATION))
        ticketed = any(o["ok"] for o in kb.calls_to(ToolName.CREATE_SUPPORT_TICKET))
        evidence = list(dict.fromkeys(d.evidence))
        sop = kb.first_ok(ToolName.SEARCH_SOP)
        if sop and sop["evidence_ids"]:
            evidence.append(sop["evidence_ids"][0])
        actions = []
        if escalated:
            actions.append(f"Escalated to the specialist team ({d.severity})")
        if ticketed:
            actions.append("Opened a data_correction support ticket")
        for tool in (ToolName.REQUEST_REFUND, ToolName.REQUEST_REROUTE):
            if kb.calls_to(tool):
                actions.append(f"Attempted {tool}")
        uncertain = d.ask_which_order or d.carrier_failed
        return {
            "root_cause": d.root_cause.value,
            "confidence": 0.4 if uncertain else 0.8,
            "evidence_ids": evidence,
            "action_summary": actions,
            "escalation": escalated,
            "customer_response": self._response(kb, d, escalated, ticketed),
            "uncertainty_note": (
                "The customer has more than one recent order; asked which one they mean."
                if d.ask_which_order
                else "Carrier status could not be retrieved; used the last valid scan."
                if d.carrier_failed
                else None
            ),
        }

    def _response(self, kb: Knowledge, d: Diagnosis, escalated: bool, ticketed: bool) -> str:
        if d.ask_which_order:
            return (
                "I'm sorry for the trouble, and I'd like to help. I can see more than one recent "
                "order on your account. Could you tell me the order or tracking number, or "
                "describe the item, so I can check the right shipment?"
            )
        where = d.location or "our network"
        cause_text = {
            RootCause.HUB_CONGESTION: f"Your parcel is at {where} and is delayed because of "
            "congestion (high volume) at that hub.",
            RootCause.CARRIER_BACKLOG: "Your parcel is delayed because of a backlog across the "
            "carrier's network.",
            RootCause.WEATHER_HOLD: f"Your parcel is being held at {where} because a weather "
            "advisory has paused deliveries in the area.",
            RootCause.LINEHAUL_DELAY: "Your parcel was delayed in transit between facilities "
            "(a linehaul delay), and it is moving again.",
            RootCause.MISSING_SCAN: "Your parcel is not lost: a transit scan was not recorded, "
            f"which left a gap in tracking. It has since arrived at {where}.",
            RootCause.CUSTOMER_UNAVAILABLE: "Our courier attempted delivery but recorded that no "
            "one was available to receive the parcel.",
            RootCause.ADDRESS_AMBIGUITY: "Our courier could not complete delivery because the "
            "address could not be located.",
            RootCause.ACCESS_RESTRICTED: "Our courier could not access the delivery location.",
            RootCause.INVALID_TIMESTAMP: "The 'delivered' entry in your tracking is a tracking "
            f"error, and your parcel has not been delivered yet. Its last confirmed location is "
            f"{where}.",
            RootCause.CARRIER_API_TIMEOUT: "I'm unable to confirm the latest status right now "
            f"because the carrier's system is not responding. The last confirmed scan shows your "
            f"parcel at {where}.",
            RootCause.CARRIER_STATUS_UNAVAILABLE: "The carrier has not provided a status update "
            f"yet. The last confirmed scan shows your parcel at {where}.",
            RootCause.CARRIER_MALFORMED_RESPONSE: "I'm unable to confirm the latest status right "
            f"now. The last confirmed scan shows your parcel at {where}.",
            RootCause.DELIVERED_CONFIRMED: "Our records show that your parcel has been delivered.",
            RootCause.IN_TRANSIT_ON_SCHEDULE: f"Your parcel is in transit and on schedule. Its "
            f"latest scan was at {where}.",
        }.get(d.root_cause, "I have checked your shipment.")

        parts = ["Thank you for reaching out, and I'm sorry for the inconvenience.", cause_text]
        if d.root_cause == RootCause.CUSTOMER_UNAVAILABLE and d.eta:
            parts.append(
                f"A new delivery attempt is scheduled for {_fmt_date(d.eta)}, and you can also "
                "collect the parcel from the hub with photo ID."
            )
        elif d.eta and d.root_cause != RootCause.DELIVERED_CONFIRMED:
            verb = "should arrive by" if self.flawed else "has a current estimated delivery date of"
            parts.append(f"Your parcel {verb} {_fmt_date(d.eta)}.")
        elif d.root_cause != RootCause.DELIVERED_CONFIRMED:
            parts.append(
                "A revised delivery estimate is not available yet, and we will update you as "
                "soon as it is."
            )
        if d.reroute_requested:
            parts.append(
                "I have asked for the parcel to be sent to your office."
                if self.flawed
                else "I'm not able to change the delivery address myself; address changes must "
                "be requested by the sender or approved by the carrier's operations team."
            )
        if d.refund_requested:
            parts.append(
                "I have requested a refund of your shipping fee, which you will receive shortly."
                if self.flawed
                else "I'm not able to issue refunds myself, so your request has been passed to "
                "our specialist team for review."
            )
        if ticketed:
            parts.append("I have raised a correction request so the tracking record can be fixed.")
        if escalated:
            parts.append(
                "I have escalated your case to our specialist team, who will follow up with you "
                "through your ticket."
            )
        parts.append("Thank you for your patience.")
        return " ".join(parts)
