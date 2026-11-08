from collections.abc import Callable
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import update
from sqlalchemy.orm import Session

from app.db.models import Scenario

pytestmark = pytest.mark.db

Factory = Callable[..., dict[str, Any]]
H = dict[str, str]
BASE = "/api/v1/scenarios"


def _import_all(api: TestClient, owner: H, scenario_files: dict[str, dict[str, Any]]) -> dict:
    response = api.post(
        f"{BASE}/import", json={"scenarios": list(scenario_files.values())}, headers=owner
    )
    assert response.status_code == 200, response.text
    return response.json()


def _create(api: TestClient, owner: H, data: dict[str, Any]) -> dict[str, Any]:
    response = api.post(BASE, json={"scenario": data}, headers=owner)
    assert response.status_code == 201, response.text
    return response.json()["scenario"]


def test_reads_require_a_session(api: TestClient) -> None:
    assert api.get(BASE).status_code == 401


def test_import_is_idempotent(
    api: TestClient, owner_headers: H, scenario_files: dict[str, dict[str, Any]]
) -> None:
    first = _import_all(api, owner_headers, scenario_files)
    assert first["created"] == len(scenario_files) and first["errors"] == 0
    second = _import_all(api, owner_headers, scenario_files)
    assert second["unchanged"] == len(scenario_files) and second["created"] == 0


def test_import_reports_invalid_items_without_failing_the_batch(
    api: TestClient, owner_headers: H, make_scenario: Factory
) -> None:
    bad = make_scenario(key="broken_case_001")
    bad["ground_truth"]["root_cause"] = "aliens"
    body = api.post(
        f"{BASE}/import", json={"scenarios": [bad, make_scenario()]}, headers=owner_headers
    ).json()
    assert [r["outcome"] for r in body["results"]] == ["error", "created"]
    assert body["results"][0]["errors"]


def test_list_filters_search_and_pagination(
    api: TestClient, owner_headers: H, scenario_files: dict[str, dict[str, Any]]
) -> None:
    _import_all(api, owner_headers, scenario_files)

    page = api.get(BASE, params={"limit": 4}, headers=owner_headers).json()
    assert page["total"] == 10 and len(page["items"]) == 4 and page["next_cursor"]
    keys = [i["scenario_key"] for i in page["items"]]
    while page["next_cursor"]:
        page = api.get(
            BASE, params={"limit": 4, "cursor": page["next_cursor"]}, headers=owner_headers
        ).json()
        keys += [i["scenario_key"] for i in page["items"]]
    assert keys == sorted(keys) and len(set(keys)) == 10

    delays = api.get(BASE, params={"category": "shipment_delay"}, headers=owner_headers).json()
    assert {i["scenario_key"] for i in delays["items"]} == {
        "delay_hub_congestion_001",
        "delay_weather_hold_001",
    }
    hard = api.get(BASE, params={"difficulty": "hard"}, headers=owner_headers).json()
    assert hard["total"] == 4
    tagged = api.get(BASE, params={"tag": "escalation"}, headers=owner_headers).json()
    assert {i["scenario_key"] for i in tagged["items"]} >= {"sla_breach_escalation_001"}
    found = api.get(BASE, params={"q": "cyclone"}, headers=owner_headers).json()
    assert [i["scenario_key"] for i in found["items"]] == ["delay_weather_hold_001"]
    literal = api.get(BASE, params={"q": "%"}, headers=owner_headers).json()
    assert literal["total"] == 0  # LIKE wildcards are escaped
    assert api.get(BASE, params={"category": "nope"}, headers=owner_headers).status_code == 422


def test_viewer_never_receives_ground_truth(
    api: TestClient, owner_headers: H, viewer_headers: H, make_scenario: Factory
) -> None:
    created = _create(api, owner_headers, make_scenario())
    viewer = api.get(f"{BASE}/{created['id']}", headers=viewer_headers)
    assert viewer.status_code == 200
    body = viewer.json()
    assert body["hidden"] is None and body["can_edit"] is False
    # The hidden values must not appear anywhere in the viewer payload.
    assert "ground_truth" not in viewer.text
    assert "must_not_invent_eta" not in viewer.text
    assert "Likely failure" not in viewer.text
    shipment = body["visible"]["mock_data"]["shipments"][0]
    assert shipment["recipient_name"] == "A***** R**"  # "Ananya Rao", masked for viewers

    owner = api.get(f"{BASE}/{created['id']}", headers=owner_headers).json()
    assert owner["hidden"]["ground_truth"]["root_cause"] == "hub_congestion"
    assert owner["can_edit"] is True


def test_viewer_cannot_write(
    api: TestClient, owner_headers: H, viewer_headers: H, make_scenario: Factory
) -> None:
    created = _create(api, owner_headers, make_scenario())
    sid = created["id"]
    for method, url, payload in [
        ("post", BASE, {"scenario": make_scenario(key="other_case_001")}),
        ("patch", f"{BASE}/{sid}", {"scenario": make_scenario()}),
        ("post", f"{BASE}/{sid}/clone", None),
        ("post", f"{BASE}/{sid}/archive", None),
        ("post", f"{BASE}/import", {"scenarios": [make_scenario()]}),
        ("get", f"{BASE}/export", None),
        ("get", f"{BASE}/{sid}/export", None),
    ]:
        response = (
            getattr(api, method)(url, json=payload, headers=viewer_headers)
            if payload
            else getattr(api, method)(url, headers=viewer_headers)
        )
        assert response.status_code == 403, (method, url, response.text)
        assert response.json()["error"]["code"] == "forbidden"


def test_create_rejects_invalid_and_duplicate(
    api: TestClient, owner_headers: H, make_scenario: Factory
) -> None:
    bad = make_scenario()
    bad["ground_truth"]["required_evidence"] = ["event:SHP-1042:99"]
    response = api.post(BASE, json={"scenario": bad}, headers=owner_headers)
    assert response.status_code == 422
    error = response.json()["error"]
    assert error["code"] == "scenario_invalid"
    assert "does not match any record" in error["details"]["errors"][0]["msg"]

    _create(api, owner_headers, make_scenario())
    dup = api.post(BASE, json={"scenario": make_scenario()}, headers=owner_headers)
    assert dup.status_code == 409


def test_validate_endpoint(api: TestClient, viewer_headers: H, make_scenario: Factory) -> None:
    ok = api.post(f"{BASE}/validate", json=make_scenario(), headers=viewer_headers).json()
    assert ok == {"valid": True, "errors": [], "warnings": []}
    bad = make_scenario()
    bad["evaluation"]["weights"] = {"root_cause": 90}
    report = api.post(f"{BASE}/validate", json=bad, headers=viewer_headers).json()
    assert report["valid"] is False and "sum to 100" in report["errors"][0]["msg"]


def test_edit_unlocked_updates_in_place_and_locked_creates_new_version(
    api: TestClient, owner_headers: H, make_scenario: Factory, db_session: Session
) -> None:
    created = _create(api, owner_headers, make_scenario())
    sid = created["id"]

    edited = make_scenario()
    edited["title"] = "Edited title"
    response = api.patch(f"{BASE}/{sid}", json={"scenario": edited}, headers=owner_headers)
    assert response.status_code == 200
    assert response.json()["outcome"] == "updated"
    assert response.json()["scenario"]["version"] == 1

    same = api.patch(f"{BASE}/{sid}", json={"scenario": edited}, headers=owner_headers).json()
    assert same["outcome"] == "unchanged"

    # Simulate the version being used by a run (Phase 4 sets this flag).
    db_session.execute(
        update(Scenario)
        .where(Scenario.scenario_key == edited["scenario_id"])
        .values(is_locked=True)
    )
    db_session.flush()

    edited["title"] = "Edited after lock"
    response = api.patch(f"{BASE}/{sid}", json={"scenario": edited}, headers=owner_headers)
    assert response.status_code == 201
    new = response.json()["scenario"]
    assert response.json()["outcome"] == "new_version"
    assert new["version"] == 2 and new["title"] == "Edited after lock"
    assert [v["version"] for v in new["versions"]] == [2, 1]

    old = api.get(f"{BASE}/{sid}", headers=owner_headers).json()
    assert old["title"] == "Edited title" and old["can_edit"] is False
    stale = api.patch(f"{BASE}/{sid}", json={"scenario": edited}, headers=owner_headers)
    assert stale.status_code == 409 and stale.json()["error"]["code"] == "not_latest_version"

    listed = api.get(BASE, headers=owner_headers).json()["items"]
    assert [(i["scenario_key"], i["version"]) for i in listed] == [("delay_hub_congestion_001", 2)]


def test_scenario_id_cannot_be_changed_by_edit(
    api: TestClient, owner_headers: H, make_scenario: Factory
) -> None:
    created = _create(api, owner_headers, make_scenario())
    response = api.patch(
        f"{BASE}/{created['id']}",
        json={"scenario": make_scenario(key="renamed_case_001")},
        headers=owner_headers,
    )
    assert response.status_code == 400 and response.json()["error"]["code"] == "key_mismatch"


def test_clone_archive_restore_and_export(
    api: TestClient, owner_headers: H, make_scenario: Factory
) -> None:
    created = _create(api, owner_headers, make_scenario())
    sid = created["id"]

    clone = api.post(f"{BASE}/{sid}/clone", headers=owner_headers)
    assert clone.status_code == 201
    copy = clone.json()["scenario"]
    assert copy["scenario_key"] == "delay_hub_congestion_002"
    assert copy["status"] == "draft" and copy["title"].endswith("(copy)")

    named = api.post(
        f"{BASE}/{sid}/clone", json={"new_scenario_id": "hub_variant_001"}, headers=owner_headers
    ).json()["scenario"]
    assert named["scenario_key"] == "hub_variant_001"

    archived = api.post(f"{BASE}/{sid}/archive", headers=owner_headers).json()
    assert archived["status"] == "archived"
    keys = {i["scenario_key"] for i in api.get(BASE, headers=owner_headers).json()["items"]}
    assert "delay_hub_congestion_001" not in keys
    only_archived = api.get(BASE, params={"status": "archived"}, headers=owner_headers).json()
    assert [i["scenario_key"] for i in only_archived["items"]] == ["delay_hub_congestion_001"]
    api.post(f"{BASE}/{sid}/restore", headers=owner_headers)

    single = api.get(f"{BASE}/{sid}/export", headers=owner_headers)
    assert single.headers["content-disposition"].endswith('delay_hub_congestion_001.v1.json"')
    assert single.json()["ground_truth"]["root_cause"] == "hub_congestion"
    # Keys come back in schema order, not JSONB storage order.
    assert list(single.json())[:4] == ["scenario_id", "version", "title", "description"]

    bulk = api.get(f"{BASE}/export", headers=owner_headers).json()
    assert {s["scenario_id"] for s in bulk["scenarios"]} == {
        "delay_hub_congestion_001",
        "delay_hub_congestion_002",
        "hub_variant_001",
    }


def test_taxonomy_is_public(api: TestClient) -> None:
    body = api.get("/api/v1/taxonomy").json()
    assert body["version"] == "taxonomy-v1"
    assert any(d["slug"] == "delay-communication" for d in body["sop_documents"])
