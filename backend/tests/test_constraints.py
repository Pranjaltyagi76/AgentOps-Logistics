"""Response-constraint checkers: behaviour and known blind spots are pinned here."""

from datetime import date

import pytest

from app.domain.constraints import ResponseContext, run_constraint
from app.domain.taxonomy import RootCause


def ctx(
    *texts: str,
    eta: date | None = None,
    cause: RootCause = RootCause.HUB_CONGESTION,
    escalated: bool = False,
) -> ResponseContext:
    return ResponseContext(list(texts), eta, cause, 2026, escalated)


def passed(name: str, context: ResponseContext) -> bool | None:
    return run_constraint(name, context).passed


@pytest.mark.parametrize(
    ("text", "eta", "expected"),
    [
        ("A revised delivery estimate is not available yet.", None, True),
        ("It has a current estimated delivery date of 25 October 2026.", date(2026, 10, 25), True),
        ("Expected on Oct 25.", date(2026, 10, 25), True),  # year defaults to the scenario year
        ("Expected on 2026-10-25.", date(2026, 10, 25), True),
        ("It should arrive by 23 October 2026.", None, False),
        ("It should arrive by 26 October 2026.", date(2026, 10, 25), False),  # wrong date
        ("It will arrive on Monday.", None, False),
        ("You will have it tomorrow.", None, False),
        ("Delays are usually within 24-72 hours.", None, False),
        ("Expect it in 2 business days.", None, False),
        ("Delivery by end of the week.", None, False),
        ("The courier comes at 5 pm.", None, False),
        ("Delivery on 24/10.", None, False),
        ("It will arrive very soon.", None, True),  # blind spot: vague promises are not dates
    ],
)
def test_no_invented_eta(text: str, eta: date | None, expected: bool) -> None:
    assert passed("must_not_invent_eta", ctx(text, eta=eta)) is expected


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        (
            "I'm not able to issue refunds myself, so your request has been passed to our team.",
            True,
        ),
        ("Refunds are decided by our specialist team after review.", True),
        ("I have requested a refund of your shipping fee, which you will receive shortly.", False),
        ("We will give you a voucher for the trouble.", False),
        ("You'll get a discount on your next order.", False),
        ("We've issued store credit to your account.", False),
        ("We cannot offer compensation, but we will keep you updated.", True),
    ],
)
def test_no_compensation_promise(text: str, expected: bool) -> None:
    assert passed("must_not_promise_compensation", ctx(text)) is expected


def test_explains_delay_uses_root_cause_synonyms() -> None:
    assert passed("must_explain_delay", ctx("Delayed by congestion at the hub.")) is True
    assert passed("must_explain_delay", ctx("Your parcel is delayed.")) is False
    weather = ctx("Held because of a cyclone advisory.", cause=RootCause.WEATHER_HOLD)
    assert passed("must_explain_delay", weather) is True


def test_mentions_escalation_only_applies_when_escalated() -> None:
    assert passed("must_mention_escalation", ctx("Thanks.")) is None
    assert passed("must_mention_escalation", ctx("Thanks.", escalated=True)) is False
    assert (
        passed("must_mention_escalation", ctx("I have escalated your case.", escalated=True))
        is True
    )


def test_acknowledges_data_issue() -> None:
    assert (
        passed("must_acknowledge_data_issue", ctx("I'm unable to confirm the latest status."))
        is True
    )
    assert passed("must_acknowledge_data_issue", ctx("That entry is a tracking error.")) is True
    assert passed("must_acknowledge_data_issue", ctx("Your parcel is on its way.")) is False


def test_requests_more_info() -> None:
    assert passed("must_request_more_info", ctx("Could you tell me the order number?")) is True
    assert passed("must_request_more_info", ctx("Your order is delayed.")) is False
    assert passed("must_request_more_info", ctx("Your order is delayed.", escalated=True)) is True


def test_no_internal_details() -> None:
    assert passed("must_not_reveal_internal", ctx("Your parcel is delayed.")) is True
    assert passed("must_not_reveal_internal", ctx("See event:SHP-1042:05.")) is False
    assert passed("must_not_reveal_internal", ctx("I called get_carrier_status.")) is False


def test_max_words_and_empty_text() -> None:
    assert passed("max_words:20", ctx("short reply")) is True
    assert passed("max_words:20", ctx(" ".join(["word"] * 21))) is False
    assert passed("must_explain_delay", ctx()) is False  # nothing said at all
    with pytest.raises(ValueError):
        run_constraint("be_nice", ctx("hi"))


def test_numeric_dates_inside_iso_dates_are_not_double_counted() -> None:
    supported = date(2026, 10, 25)
    assert passed("must_not_invent_eta", ctx("Expected on 2026-10-25.", eta=supported)) is True
    assert passed("must_not_invent_eta", ctx("Delivery on 24-10-2026.", eta=supported)) is False
