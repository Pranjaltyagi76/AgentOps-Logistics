"""Writes trace events as they happen, each in its own short transaction.

Writing immediately (instead of at the end) means a run that crashes or is killed still leaves
a partial trace. Events hold only observable data: the agent input, agent turns (visible text
and tool calls), tool calls with results/errors, limits, the outcome and run status changes.
No hidden reasoning is requested or stored (PROJECT.md FR-05).
"""

import threading
import uuid
from collections.abc import Callable, Iterable
from contextlib import AbstractContextManager
from typing import Any

from sqlalchemy.orm import Session

from app.db.models import TraceEvent
from app.services.tools.gateway import ToolCallRecord

SessionFactory = Callable[[], AbstractContextManager[Session]]


class TraceCollector:
    def __init__(
        self, run_id: uuid.UUID, session_factory: SessionFactory, start_seq: int = 0
    ) -> None:
        self.run_id = run_id
        self._session_factory = session_factory
        self._seq = start_seq
        self._lock = threading.Lock()

    @property
    def last_seq(self) -> int:
        return self._seq

    def emit(
        self,
        event_type: str,
        *,
        node: str | None = None,
        tool: str | None = None,
        input: Any = None,
        output: Any = None,
        error: dict[str, Any] | None = None,
        evidence_ids: Iterable[str] = (),
        duration_ms: int | None = None,
        usage: dict[str, Any] | None = None,
    ) -> int:
        with self._lock:
            self._seq += 1
            seq = self._seq
        with self._session_factory() as db:
            db.add(
                TraceEvent(
                    run_id=self.run_id,
                    seq=seq,
                    event_type=event_type,
                    node_name=node,
                    tool_name=tool,
                    input_json=input,
                    output_json=output,
                    error_json=error,
                    evidence_ids=list(evidence_ids),
                    duration_ms=duration_ms,
                    usage_json=usage,
                )
            )
            db.commit()
        return seq

    # Gateway observer: one event per tool call, including rejected ones.
    def on_tool_call(self, record: ToolCallRecord) -> None:
        body = record.outcome.model_dump(mode="json")
        if record.ok:
            event_type, output, error = "tool_result", body["data"], None
        else:
            event_type = "policy_denied" if body["code"] == "policy_denied" else "tool_error"
            output = None
            error = {k: body[k] for k in ("code", "message", "retryable", "details")}
        self.emit(
            event_type,
            node="act",
            tool=record.tool,
            input={
                "arguments": record.arguments,
                "call_seq": record.seq,
                "simulated_latency_ms": record.simulated_latency_ms,
            },
            output=output,
            error=error,
            evidence_ids=body.get("evidence_ids", []),
            duration_ms=record.duration_ms,
        )

    # Graph hook: agent input, turns, limits and outcomes.
    def on_graph_event(self, event_type: str, node: str | None, payload: dict[str, Any]) -> None:
        if event_type == "agent_input":
            self.emit(event_type, node=node, input=payload)
        elif event_type == "agent_turn":
            self.emit(
                event_type,
                node=node,
                output={k: payload[k] for k in ("step", "text", "tool_calls", "model_id")},
                usage=payload.get("usage"),
                duration_ms=payload.get("duration_ms"),
            )
        elif event_type == "outcome_submitted":
            self.emit(
                event_type, node=node, output=payload, evidence_ids=payload.get("evidence_ids", [])
            )
        elif event_type == "outcome_invalid":
            self.emit(
                event_type,
                node=node,
                input=payload.get("arguments"),
                error={
                    "code": "invalid_outcome",
                    "problems": payload.get("problems", []),
                    "final": payload.get("final"),
                },
            )
        else:  # limit_exceeded and anything new
            self.emit(event_type, node=node, output=payload)
