"""Read-only view of a scenario's mock data, the only thing tool handlers can see.

It is built from the scenario but structurally has no access to ground truth, evaluation
rules or author notes (decision D-04): tools cannot leak answers even by mistake.
"""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from app.schemas.scenario import (
    CarrierStatus,
    FaultInjection,
    ScenarioSpec,
    Shipment,
    Ticket,
    TrackingEvent,
)


@dataclass(frozen=True)
class ScenarioDataView:
    scenario_id: str
    as_of: datetime
    shipments: dict[str, Shipment]
    events: tuple[TrackingEvent, ...]
    carriers: dict[str, CarrierStatus]
    tickets: dict[str, Ticket]
    permitted_documents: frozenset[str]
    available_tools: frozenset[str]
    fault_injection: tuple[FaultInjection, ...] = field(default_factory=tuple)

    @classmethod
    def from_spec(cls, spec: ScenarioSpec) -> "ScenarioDataView":
        data = spec.mock_data
        return cls(
            scenario_id=spec.scenario_id,
            as_of=spec.as_of,
            shipments={s.shipment_id: s for s in data.shipments},
            events=tuple(sorted(data.tracking_events, key=lambda e: (e.shipment_id, e.seq))),
            carriers={c.carrier_id: c for c in data.carrier_status},
            tickets={t.ticket_id: t for t in data.tickets},
            permitted_documents=frozenset(spec.permitted_documents),
            available_tools=frozenset(spec.available_tools),
            fault_injection=tuple(spec.fault_injection),
        )

    def events_for(self, shipment_id: str) -> list[TrackingEvent]:
        return [e for e in self.events if e.shipment_id == shipment_id]


def as_json(model: Any) -> dict[str, Any]:
    return model.model_dump(mode="json")
