from typing import Any

import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr, ValidationError
from sqlalchemy import update
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.db.models import AgentConfig
from app.schemas.agent_config import AgentConfigSpec, load_prompt

H = dict[str, str]
BASE = "/api/v1/agents"
CONFIG: dict[str, Any] = {
    "name": "rule-based-test",
    "description": "Test agent",
    "provider": "rule_based",
    "model_id": "v1",
    "max_steps": 10,
}


# --- schema (unit) ------------------------------------------------------------------------


def test_spec_defaults_and_prompt_resolution() -> None:
    spec = AgentConfigSpec.model_validate(CONFIG)
    assert spec.version == 1 and spec.temperature == 0
    assert spec.system_prompt == load_prompt("agent_system_v1")
    assert len(spec.tools) == 10 and spec.max_tool_calls == 10


@pytest.mark.parametrize(
    ("change", "message"),
    [
        ({"model_id": "v9"}, "rule_based model_id must be one of"),
        ({"name": "Bad Name"}, "name"),
        ({"tools": ["get_shipment", "get_shipment"]}, "duplicates"),
        ({"tools": ["drop_table"]}, "tools"),
        ({"max_steps": 99}, "max_steps"),
        ({"prompt_version": "missing_prompt"}, "unknown prompt_version"),
        ({"provider": "anthropic_magic"}, "provider"),
        ({"api_key": "sk-123"}, "Extra inputs are not permitted"),
    ],
)
def test_spec_rejects_bad_configs(change: dict[str, Any], message: str) -> None:
    with pytest.raises(ValidationError, match=message):
        AgentConfigSpec.model_validate({**CONFIG, **change})


# --- API (database) -----------------------------------------------------------------------


@pytest.mark.db
def test_create_read_and_viewer_access(
    api: TestClient, owner_headers: H, viewer_headers: H
) -> None:
    created = api.post(BASE, json=CONFIG, headers=owner_headers)
    assert created.status_code == 201, created.text
    agent = created.json()["agent"]
    assert (agent["name"], agent["version"], agent["provider"]) == (
        "rule-based-test",
        1,
        "rule_based",
    )
    assert agent["config"]["system_prompt"].startswith("You are a customer support agent")

    listed = api.get(BASE, headers=viewer_headers).json()
    assert [a["name"] for a in listed] == ["rule-based-test"]
    detail = api.get(f"{BASE}/{agent['id']}", headers=viewer_headers).json()
    assert detail["can_edit"] is False

    for method, url, body in [
        ("post", BASE, {**CONFIG, "name": "another-one"}),
        ("patch", f"{BASE}/{agent['id']}", CONFIG),
        ("post", f"{BASE}/{agent['id']}/clone", None),
        ("post", f"{BASE}/{agent['id']}/archive", None),
    ]:
        kwargs = {"json": body} if body is not None else {}
        response = getattr(api, method)(url, headers=viewer_headers, **kwargs)
        assert response.status_code == 403, (method, url)

    assert api.post(BASE, json=CONFIG, headers=owner_headers).status_code == 409


@pytest.mark.db
def test_invalid_config_is_rejected_with_field_errors(api: TestClient, owner_headers: H) -> None:
    response = api.post(BASE, json={**CONFIG, "model_id": "v9"}, headers=owner_headers)
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "agent_invalid"
    report = api.post(
        f"{BASE}/validate", json={**CONFIG, "max_steps": 0}, headers=owner_headers
    ).json()
    assert report["valid"] is False and report["errors"][0]["loc"] == "max_steps"


@pytest.mark.db
def test_versioning_clone_archive(api: TestClient, owner_headers: H, db_session: Session) -> None:
    agent = api.post(BASE, json=CONFIG, headers=owner_headers).json()["agent"]
    aid = agent["id"]

    edited = api.patch(f"{BASE}/{aid}", json={**CONFIG, "max_steps": 12}, headers=owner_headers)
    assert edited.status_code == 200 and edited.json()["outcome"] == "updated"
    same = api.patch(f"{BASE}/{aid}", json={**CONFIG, "max_steps": 12}, headers=owner_headers)
    assert same.json()["outcome"] == "unchanged"

    db_session.execute(
        update(AgentConfig).where(AgentConfig.name == "rule-based-test").values(is_locked=True)
    )
    db_session.flush()
    bumped = api.patch(f"{BASE}/{aid}", json={**CONFIG, "max_steps": 14}, headers=owner_headers)
    assert bumped.status_code == 201
    new = bumped.json()["agent"]
    assert new["version"] == 2 and new["config"]["max_steps"] == 14
    assert [v["version"] for v in new["versions"]] == [2, 1]
    stale = api.patch(f"{BASE}/{aid}", json=CONFIG, headers=owner_headers)
    assert stale.status_code == 409

    renamed = api.patch(
        f"{BASE}/{new['id']}", json={**CONFIG, "name": "other"}, headers=owner_headers
    )
    assert renamed.json()["error"]["code"] == "name_mismatch"

    clone = api.post(f"{BASE}/{aid}/clone", headers=owner_headers).json()["agent"]
    assert clone["name"] == "rule-based-test-copy" and clone["version"] == 1

    api.post(f"{BASE}/{aid}/archive", headers=owner_headers)
    names = [a["name"] for a in api.get(BASE, headers=owner_headers).json()]
    assert names == ["rule-based-test-copy"]
    with_archived = api.get(BASE, params={"include_archived": True}, headers=owner_headers).json()
    assert {a["name"] for a in with_archived} == {"rule-based-test", "rule-based-test-copy"}


@pytest.mark.db
def test_provider_status_never_reveals_keys(
    db_session: Session, test_settings: Settings, viewer_headers: H
) -> None:
    from fastapi.testclient import TestClient as Client

    from app.db.session import get_db
    from app.main import create_app

    settings = test_settings.model_copy(update={"gemini_api_key": SecretStr("AIza-secret-value")})
    app = create_app(settings)
    app.dependency_overrides[get_db] = lambda: db_session
    with Client(app) as client:
        response = client.get(f"{BASE}/providers", headers=viewer_headers)
    body = {p["provider"]: p for p in response.json()}
    assert body["rule_based"]["available"] is True
    assert body["gemini"]["configured"] is True and body["gemini"]["available"] is True
    assert body["gemini"]["runs_left_today"] is None  # viewers can't launch LLM runs
    assert body["openai"]["available"] is False
    assert "AIza" not in response.text and "secret-value" not in response.text
