"""Deterministic, no-LLM agents (decision D-05).

They read only the agent input and tool observations, exactly like an LLM agent would, and
are labelled "rule-based baseline" everywhere: they validate the platform and give a free
demo; they are not evidence of AI capability.

Profiles:
- "v1":        follows the SOPs: gathers evidence, retries a timed-out carrier call once,
               spots invalid timestamps, searches the relevant SOP, escalates per policy.
               Phase 10 added rules for the expanded set (duplicate / out-of-order scans,
               stale and conflicting ETAs, inconsistent statuses, missing IDs, SLA risk,
               safety reports, repeat complaints, delivery disputes, unexplained holds);
               a golden test keeps its results on the 10 MVP scenarios unchanged.
- "v2_flawed": the same agent with realistic bugs (skips SOP search, ignores tool errors,
               trusts impossible timestamps and records, quotes the promised date as an ETA,
               guesses between orders, tries to refund/reroute when asked, and follows
               refund instructions it finds inside tool results). Used to demonstrate a
               reproducible regression.
"""

import re
from dataclasses import dataclass, field
from datetime import date, datetime
from itertools import pairwise
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
_SAFETY = re.compile(
    r"\b(leak\w*|chemical|smell\w*|fire|smok\w*|injur\w*|hurt|unsafe|hazard\w*|toxic|burn\w*)",
    re.IGNORECASE,
)
_REPEAT = re.compile(
    r"\b(third|fourth|fifth|second) (time|contact)|\b(again and again|several times|contacted you"
    r" (\w+ )?times|keep contacting)",
    re.IGNORECASE,
)
_NOT_RECEIVED = re.compile(
    r"\b(never (received|got)|not received|didn't (receive|get)|did not (receive|get)|haven't"
    r" (received|got))",
    re.IGNORECASE,
)
_ISO_DATE = re.compile(r"\b(20\d\d-\d\d-\d\d)\b")
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
    # Phase 10 situations (the MVP ones above are unchanged).
    "carrier_malformed": "carrier returns a response that cannot be read malformed",
    "carrier_unavailable": "carrier reports that it has no status for the shipment",
    "duplicate_scan": "same scan recorded twice duplicate scans",
    "out_of_order": "tracking events out of time order recorded late",
    "eta_stale": "estimated delivery date already in the past stale ETA",
    "eta_conflict": "shipment record and carrier update give different delivery dates conflicting",
    "inconsistent": "shipment record and latest valid tracking event disagree inconsistent status",
    "missing_id": "customer does not give a shipment or tracking number missing identifiers",
    "unconfirmed": "no cause is confirmed say the delay is being investigated",
    "sla_at_risk": "express shipment at risk of missing its promised date escalate proactively",
    "safety": "safety or legal concern reported mandatory escalation triggers",
    "repeat": "customer contacted support two or more times repeated complaints",
    "dispute": "tracking shows delivered but the customer did not receive it delivery disputes",
    "reroute": "change delivery address reroute redirection authorization",
    "on_track": "status enquiries for shipments on track latest scan location",
}
_CARRIER_FAILURE_SITUATION = {
    "malformed_response": "carrier_malformed",
    "unavailable": "carrier_unavailable",
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
    ask_for_id: bool = False  # no shipment or tracking number at all (Phase 10)
    ticket_category: str = "data_correction"
    safety_report: bool = False
    repeat_contact: bool = False


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
        ticket = self._ticket(kb)
        if kb.context.get("shipment_id"):
            # v1: the chat context and the open ticket point at different shipments -> ask.
            # (v2 trusts the context.)
            if (
                not self.flawed
                and ticket is not None
                and ticket.get("shipment_id")
                and ticket["shipment_id"] != kb.context["shipment_id"]
            ):
                return None
            return kb.context["shipment_id"]
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
            if (
                ticket is None
                and not kb.context.get("shipment_id")
                and not kb.context.get("ticket_id")
            ):
                return Diagnosis(
                    RootCause.MISSING_TRACKING_ID,
                    "missing_id",
                    ask_for_id=True,
                    refund_requested=refund,
                    reroute_requested=reroute,
                )
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
            d.root_cause = _CARRIER_FAILURE_CAUSE[carrier_error]
            d.situation = _CARRIER_FAILURE_SITUATION.get(carrier_error, "carrier_failure")
            d.carrier_failed = True
            d.evidence += [last["evidence_id"]] if last else []
            past_promise = kb.now.date() > date.fromisoformat(shipment["promised_delivery_date"])
            if hours is not None and hours > 24:
                d.escalate, d.severity = True, "medium"
                d.escalation_reason = (
                    f"Carrier status could not be confirmed ({carrier_error}) and there has been "
                    f"no new scan for {hours:.0f} hours"
                )
            elif carrier_error == "unavailable" and past_promise:  # carrier-integration s4
                d.escalate, d.severity = True, "medium"
                d.escalation_reason = (
                    "Carrier has no status for a shipment past its promised date "
                    f"({shipment['promised_delivery_date']})"
                )
                d.evidence.append(f"shipment:{shipment['shipment_id']}")
        elif not self.flawed and self._data_anomaly(kb, d, shipment, events):
            pass  # handled: duplicate / out-of-order scans, stale or conflicting ETA, bad status
        else:
            self._diagnose_from_events(d, valid, carrier_ok)

        self._apply_sla(kb, d, shipment)
        if not self.flawed:
            self._apply_contact_rules(kb, d, valid)
        if self.flawed and not refund:  # v2 obeys refund instructions found inside tool results
            texts = [((carrier_ok or {}).get("data") or {}).get("notice") or ""]
            ticket = self._ticket(kb) or {}
            texts += [ticket.get("last_customer_message") or "", ticket.get("subject") or ""]
            refund = d.refund_requested = any(_REFUND.search(t) for t in texts)
        if refund and not self.flawed:
            d.situation = "refund" if d.situation in ("delay", "sla_breach") else d.situation
            if not d.escalate:
                d.escalate, d.severity = True, "high"
                d.escalation_reason = "Customer requests a refund or compensation"
        if d.situation == "delay" and reroute and not refund:
            d.situation = "reroute"
        elif d.situation == "delay" and d.root_cause == RootCause.IN_TRANSIT_ON_SCHEDULE:
            d.situation = "on_track"
        d.eta = self._eta(shipment, d)
        return d

    def _data_anomaly(
        self, kb: Knowledge, d: Diagnosis, shipment: dict[str, Any], events: list[dict[str, Any]]
    ) -> bool:
        """v1 checks for recording problems before reading a cause from the events (Phase 10)."""
        if not events:
            return False
        last = events[-1]
        if shipment["status"] == "delivered" and not any(
            e["event_code"] == "DELIVERED" for e in events
        ):
            d.root_cause, d.situation = RootCause.INCONSISTENT_STATUS, "inconsistent"
            d.location = last["location"]
            d.evidence.append(last["evidence_id"])
            d.data_ticket = (
                f"Shipment {shipment['shipment_id']} has status 'delivered' but there is no "
                f"delivery scan; the latest scan is {last['event_code']} at {last['location']}. "
                "Please reconcile the shipment record."
            )
            return True
        for previous, event in pairwise(events):
            gap = (_parse_dt(event["timestamp"]) - _parse_dt(previous["timestamp"])).total_seconds()
            same = (event["event_code"], event["location"]) == (
                previous["event_code"],
                previous["location"],
            )
            if same and 0 <= gap <= 600:
                d.root_cause, d.situation = RootCause.DUPLICATE_SCAN, "duplicate_scan"
                d.evidence += [previous["evidence_id"], event["evidence_id"]]
                return True
            if gap < 0:
                latest = max(events, key=lambda e: _parse_dt(e["timestamp"]))
                d.root_cause, d.situation = RootCause.OUT_OF_ORDER_EVENTS, "out_of_order"
                d.location = latest["location"]
                d.evidence += [latest["evidence_id"], event["evidence_id"]]
                return True
        revised = next((e for e in events if e["event_code"] == "ETA_REVISED"), None)
        match = _ISO_DATE.search(revised["description"]) if revised else None
        if (
            revised
            and match
            and shipment.get("current_eta")
            and match.group(1) != shipment["current_eta"]
        ):
            d.root_cause, d.situation = RootCause.CONFLICTING_ETA_SOURCES, "eta_conflict"
            d.evidence.append(revised["evidence_id"])
            d.data_ticket = (
                f"Shipment {shipment['shipment_id']} shows ETA {shipment['current_eta']} but a "
                f"carrier update revised it to {match.group(1)}. Please reconcile the delivery "
                "date."
            )
            return True
        eta = shipment.get("current_eta")
        if (
            eta
            and shipment.get("eta_status") in ("confirmed", "estimated")
            and shipment["status"] != "delivered"
            and date.fromisoformat(eta) < kb.now.date()
        ):
            d.root_cause, d.situation = RootCause.STALE_ETA, "eta_stale"
            return True
        return False

    def _apply_contact_rules(
        self, kb: Knowledge, d: Diagnosis, events: list[dict[str, Any]]
    ) -> None:
        """v1: safety reports, SLA risk, repeat complaints and delivery disputes (Phase 10)."""
        ticket = self._ticket(kb) or {}
        if _SAFETY.search(kb.message):
            d.safety_report = True
            d.situation = "safety"
            d.escalate, d.severity = True, "critical"
            d.escalation_reason = (
                "Customer reports a safety concern with the parcel (possible hazard)"
            )
            return
        if d.root_cause == RootCause.DELIVERED_CONFIRMED and _NOT_RECEIVED.search(kb.message):
            d.situation = "dispute"
            d.ticket_category = "delivery_issue"
            d.data_ticket = (
                "Customer reports the parcel marked delivered was not received; please investigate "
                "the delivery scan."
            )
        repeat_text = " ".join(
            [kb.message, ticket.get("subject") or "", ticket.get("last_customer_message") or ""]
        )
        if _REPEAT.search(repeat_text) and not d.escalate:
            d.repeat_contact = True
            d.situation = "repeat"
            d.escalate, d.severity = True, "low"
            d.escalation_reason = "Customer has contacted support repeatedly about this shipment"
            if ticket.get("ticket_id"):
                d.evidence.append(f"ticket:{ticket['ticket_id']}")

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
            elif code == "ON_HOLD" and ":" not in event["description"]:
                cause, situation = (
                    RootCause.INSUFFICIENT_EVIDENCE,
                    "unconfirmed",
                )  # no stated reason
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
        elif express and days_late == 0 and not d.escalate and not self.flawed:
            # sla-risk s2: express, within 12 h of the end of its promised day, not out for delivery
            obs = kb.first_ok(ToolName.GET_TRACKING_EVENTS)
            codes = {e["event_code"] for e in (obs["data"]["events"] if obs else [])}
            if 24 - (kb.now.hour + kb.now.minute / 60) <= 12 and "OUT_FOR_DELIVERY" not in codes:
                d.escalate, d.severity = True, "medium"
                d.escalation_reason = (
                    f"Express shipment due {shipment['promised_delivery_date']} is at risk: "
                    "no out-for-delivery scan within 12 hours of the deadline"
                )
                d.situation = "sla_at_risk"
                d.evidence.append(f"shipment:{shipment['shipment_id']}")

    def _eta(self, shipment: dict[str, Any], d: Diagnosis) -> str | None:
        if d.root_cause == RootCause.CUSTOMER_UNAVAILABLE and shipment.get("next_attempt_date"):
            return shipment["next_attempt_date"]
        if self.flawed:  # v2 falls back to the original promised date
            return shipment.get("current_eta") or shipment.get("promised_delivery_date")
        if d.situation in (
            "data_issue",
            "carrier_failure",
            "carrier_malformed",
            "carrier_unavailable",
            "eta_stale",
            "eta_conflict",
            "inconsistent",
            "unconfirmed",
        ):
            return None
        if shipment.get("eta_status") in ("confirmed", "estimated"):
            return shipment.get("current_eta")
        return None

    # --- act --------------------------------------------------------------------------------

    def _next_action(self, kb: Knowledge, d: Diagnosis) -> ToolCallRequest | None:
        if (
            not self.flawed
            and (not d.ask_which_order or d.ask_for_id)
            and kb.can(ToolName.SEARCH_SOP)
            and not kb.calls_to(ToolName.SEARCH_SOP)
        ):
            return call(ToolName.SEARCH_SOP, {"query": _SOP_QUERIES[d.situation], "top_k": 3})
        shipment_id = self._shipment_id(kb)

        def todo(tool: ToolName, wanted: bool) -> bool:
            return wanted and kb.can(tool) and not kb.calls_to(tool)

        if todo(ToolName.CREATE_SUPPORT_TICKET, d.data_ticket is not None):
            args = {"category": d.ticket_category, "summary": d.data_ticket}
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
            actions.append(f"Opened a {d.ticket_category} support ticket")
        for tool in (ToolName.REQUEST_REFUND, ToolName.REQUEST_REROUTE):
            if kb.calls_to(tool):
                actions.append(f"Attempted {tool}")
        uncertain = d.ask_which_order or d.ask_for_id or d.carrier_failed
        return {
            "root_cause": d.root_cause.value,
            "confidence": 0.4 if uncertain else 0.8,
            "evidence_ids": evidence,
            "action_summary": actions,
            "escalation": escalated,
            "customer_response": self._response(kb, d, escalated, ticketed),
            "uncertainty_note": (
                "No shipment or tracking number was given; asked the customer for it."
                if d.ask_for_id
                else "The customer has more than one recent order; asked which one they mean."
                if d.ask_which_order
                else "Carrier status could not be retrieved; used the last valid scan."
                if d.carrier_failed
                else None
            ),
        }

    def _response(self, kb: Knowledge, d: Diagnosis, escalated: bool, ticketed: bool) -> str:
        if d.ask_for_id:
            return (
                "I'm sorry your parcel hasn't arrived yet, and I'd like to help. Could you share "
                "the order or tracking number, or describe the item, so I can check the right "
                "shipment?"
            )
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
            RootCause.CARRIER_BACKLOG: "Your parcel is delayed because of a carrier backlog: the "
            "carrier has a backlog across its whole network.",
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
            RootCause.DUPLICATE_SCAN: f"Your parcel did not go back: its arrival at {where} was "
            "recorded twice, and the second entry is a duplicate scan.",
            RootCause.OUT_OF_ORDER_EVENTS: "One tracking update was recorded late, so your "
            f"tracking appears out of order. Your parcel's latest position is {where}.",
            RootCause.STALE_ETA: "The earlier delivery estimate is outdated and is being updated. "
            f"Your parcel's latest scan was at {where}.",
            RootCause.CONFLICTING_ETA_SOURCES: "Our records currently show conflicting delivery "
            "estimates, so I can't confirm a date yet; the delivery date is being confirmed.",
            RootCause.INCONSISTENT_STATUS: "Our records are inconsistent: the shipment status does "
            f"not match the latest scan, which shows your parcel at {where}. This information is "
            "being checked.",
            RootCause.INSUFFICIENT_EVIDENCE: f"Your parcel is on hold at {where}. The reason has "
            "not been confirmed yet, and we are looking into it.",
        }.get(d.root_cause, "I have checked your shipment.")

        parts = ["Thank you for reaching out, and I'm sorry for the inconvenience.", cause_text]
        if d.safety_report:
            parts = [
                "Thank you for telling us, and I'm sorry this happened. For your safety, please do "
                "not handle the parcel or its contents further.",
                cause_text,
            ]
        if d.repeat_contact:
            parts.insert(1, "I'm sorry you have had to contact us several times about this.")
        if d.situation == "dispute":
            parts.append(
                "I understand you have not received it, and I have opened an investigation with "
                "the carrier so the delivery can be checked."
            )
        if d.situation == "sla_at_risk":
            parts.append("I have asked for your shipment to be prioritised.")
        if d.root_cause == RootCause.CUSTOMER_UNAVAILABLE and d.eta:
            parts.append(
                f"A new delivery attempt is scheduled for {_fmt_date(d.eta)}, and you can also "
                "collect the parcel from the hub with photo ID."
            )
        elif d.safety_report or d.situation == "dispute":
            pass
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
        if ticketed and d.ticket_category == "data_correction":
            parts.append("I have raised a correction request so the tracking record can be fixed.")
        if escalated:
            parts.append(
                "I have escalated your case to our specialist team, who will follow up with you "
                "through your ticket."
            )
        parts.append("Thank you for your patience.")
        return " ".join(parts)
