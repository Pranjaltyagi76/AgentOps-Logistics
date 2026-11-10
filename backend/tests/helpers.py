"""Helpers shared by the run and evaluation tests."""

import uuid
from typing import Any

from fastapi.testclient import TestClient

H = dict[str, str]
RUNS = "/api/v1/runs"


def launch(
    api: TestClient,
    headers: H,
    ids: dict[str, uuid.UUID],
    scenario: str,
    agent: str = "rule-based-v1",
):  # type: ignore[no-untyped-def]
    return api.post(
        RUNS,
        json={"scenario_id": str(ids[scenario]), "agent_config_id": str(ids[agent])},
        headers=headers,
    )


def trace(api: TestClient, headers: H, run_id: str, **params: Any) -> list[dict[str, Any]]:
    response = api.get(f"{RUNS}/{run_id}/trace", params=params, headers=headers)
    assert response.status_code == 200, response.text
    return response.json()["events"]
