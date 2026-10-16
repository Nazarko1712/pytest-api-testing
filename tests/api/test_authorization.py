"""Authorization matrix.

The question is not "does the endpoint work" but "does it refuse the people it
should". A write endpoint that works perfectly for an anonymous caller is
working exactly as designed and still a breach.
"""

from __future__ import annotations

from typing import Any

import pytest

from src.client import Booking, BookingClient, BookingDates, UnexpectedStatus


@pytest.mark.smoke
def test_valid_credentials_issue_a_token(client: BookingClient) -> None:
    issued = client.authenticate()

    assert isinstance(issued, str)
    assert len(issued) > 0


def test_wrong_password_does_not_issue_a_token(client: BookingClient) -> None:
    # The API answers 200 with a `reason` body instead of 401, so the absence of
    # a token is what has to be asserted. See test_known_defects.py.
    with pytest.raises(KeyError):
        client.authenticate(password="definitely-wrong")


@pytest.mark.parametrize(
    "bad_token",
    ["", "not-a-real-token", "a" * 200],
    ids=["no-token", "forged-token", "overlong-token"],
)
@pytest.mark.parametrize(
    "operation",
    ["put", "patch", "delete"],
)
def test_writes_are_refused_without_a_valid_token(
    client: BookingClient,
    created_booking: dict[str, Any],
    operation: str,
    bad_token: str,
) -> None:
    """Stacked ``parametrize`` decorators produce the CARTESIAN PRODUCT.

    Three tokens by three operations is nine tests from one body, each reported
    with its own id — the pytest equivalent of a hand-written matrix, without
    the hand-writing.

    This is also the honest way to cover an authorization matrix: it is very
    easy to test the happy path of each write and quietly never check that the
    other two reject a forged token.
    """
    booking_id = created_booking["id"]
    replacement = Booking(
        firstname="Mallory",
        lastname="Attacker",
        totalprice=1,
        depositpaid=False,
        bookingdates=BookingDates(checkin="2026-11-01", checkout="2026-11-02"),
    )

    # The dispatch is resolved BEFORE the raises block rather than inside it.
    # Ruff's PT012 is right about why: any extra statement inside the block can
    # itself raise the expected exception, and the test then passes for a reason
    # that has nothing to do with the operation under test. One call inside the
    # block means the assertion is unambiguous.
    operations = {
        "put": lambda: client.replace(booking_id, replacement, bad_token),
        "patch": lambda: client.update(booking_id, {"totalprice": 1}, bad_token),
        "delete": lambda: client.delete(booking_id, bad_token, expected=201),
    }

    with pytest.raises(UnexpectedStatus) as failure:
        operations[operation]()

    assert failure.value.actual == 403


def test_writes_succeed_with_a_valid_token(
    client: BookingClient, created_booking: dict[str, Any], token: str
) -> None:
    """The positive half of the matrix.

    Without it, the 403s above could equally be caused by a malformed request —
    this proves the refusals are specifically about authorization.
    """
    client.update(created_booking["id"], {"totalprice": 7}, token)

    assert client.get(created_booking["id"])["totalprice"] == 7


def test_reads_stay_public(client: BookingClient, created_booking: dict[str, Any]) -> None:
    booking = client.get(created_booking["id"])

    assert booking["firstname"] == created_booking["payload"].firstname
