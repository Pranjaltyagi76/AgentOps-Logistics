import pytest

from app.domain.taxonomy import (
    ACTION_TOOLS,
    POLICY_GATED_TOOLS,
    READ_TOOLS,
    ROOT_CAUSE_INFO,
    RootCause,
    ToolName,
    evidence_kind,
    is_valid_response_constraint,
    taxonomy_payload,
)


def test_every_root_cause_has_info_and_synonyms() -> None:
    assert set(ROOT_CAUSE_INFO) == set(RootCause)
    for info in ROOT_CAUSE_INFO.values():
        assert info.synonyms, info
        assert all(s == s.lower() for s in info.synonyms)


def test_tool_groups_partition_the_registry() -> None:
    assert set(ToolName) == READ_TOOLS | ACTION_TOOLS
    assert not READ_TOOLS & ACTION_TOOLS
    assert POLICY_GATED_TOOLS <= ACTION_TOOLS


@pytest.mark.parametrize(
    ("evidence_id", "kind"),
    [
        ("shipment:SHP-1042", "shipment"),
        ("event:SHP-1042:07", "event"),
        ("carrier:CAR-SWIFT", "carrier"),
        ("ticket:TKT-0088", "ticket"),
        ("sop:delay-communication#s3", "sop"),
        ("event:SHP-1042:7", None),  # seq must be two digits
        ("shipment:shp-1042", None),  # IDs are upper case
        ("sop:delay-communication", None),  # section required
        ("te:12", None),  # trace refs are not evidence IDs
    ],
)
def test_evidence_id_parsing(evidence_id: str, kind: str | None) -> None:
    assert evidence_kind(evidence_id) == kind


def test_response_constraint_names() -> None:
    assert is_valid_response_constraint("must_not_invent_eta")
    assert is_valid_response_constraint("max_words:180")
    assert not is_valid_response_constraint("max_words:")
    assert not is_valid_response_constraint("be_nice")


def test_taxonomy_payload_is_serializable() -> None:
    payload = taxonomy_payload()
    assert len(payload["root_causes"]) == len(RootCause)  # type: ignore[arg-type]
    gated = {t["name"] for t in payload["tools"] if t["policy_gated"]}  # type: ignore[union-attr]
    assert gated == {"request_refund", "request_reroute"}
