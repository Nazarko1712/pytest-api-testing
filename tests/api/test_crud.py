"""Booking CRUD.

Mirrors ``tests/bookings/crud.spec.ts`` in the Jest project, so the two can be
read side by side.
"""

from __future__ import annotations

from typing import Any

import pytest

from src.client import Booking, BookingClient, BookingDates
from src.schemas import (
    BOOKING_ID_LIST_SCHEMA,
    BOOKING_SCHEMA,
    CREATED_BOOKING_SCHEMA,
    assert_matches,
)


@pytest.mark.smoke
def test_create_echoes_the_payload_back_unchanged(
    client: BookingClient, new_booking: Booking, token: str
) -> None:
    created = client.create(new_booking)

    try:
        assert_matches(created, CREATED_BOOKING_SCHEMA)
        assert isinstance(created["bookingid"], int)
        assert created["booking"] == new_booking.payload()
    finally:
        client.delete(created["bookingid"], token)


@pytest.mark.smoke
def test_read_returns_what_was_created(
    client: BookingClient, created_booking: dict[str, Any]
) -> None:
    fetched = client.get(created_booking["id"])

    assert_matches(fetched, BOOKING_SCHEMA)
    assert fetched == created_booking["payload"].payload()


def test_put_replaces_every_field(
    client: BookingClient, created_booking: dict[str, Any], token: str
) -> None:
    replacement = Booking(
        firstname="Ada",
        lastname="Lovelace",
        totalprice=999,
        depositpaid=True,
        bookingdates=BookingDates(checkin="2026-12-01", checkout="2026-12-05"),
        additionalneeds="Breakfast",
    )

    updated = client.replace(created_booking["id"], replacement, token)

    assert_matches(updated, BOOKING_SCHEMA)
    assert updated == replacement.payload()


def test_patch_changes_only_the_supplied_fields(
    client: BookingClient, created_booking: dict[str, Any], token: str
) -> None:
    original = created_booking["payload"]

    updated = client.update(created_booking["id"], {"totalprice": 1}, token)

    # The PUT/PATCH distinction, asserted rather than assumed: everything except
    # the patched field must survive untouched.
    assert updated["totalprice"] == 1
    assert updated["firstname"] == original.firstname
    assert updated["lastname"] == original.lastname
    assert updated["bookingdates"] == original.payload()["bookingdates"]


def test_delete_removes_the_booking(
    client: BookingClient, new_booking: Booking, token: str
) -> None:
    created = client.create(new_booking)

    client.delete(created["bookingid"], token)

    client.get(created["bookingid"], expected=404)


def test_absent_optional_field_stays_absent(client: BookingClient, token: str) -> None:
    payload = Booking(
        firstname="NoExtras",
        lastname="Testsson",
        totalprice=100,
        depositpaid=False,
        bookingdates=BookingDates(checkin="2026-11-01", checkout="2026-11-03"),
        additionalneeds=None,
    )

    created = client.create(payload)

    try:
        # An omitted optional field must not come back as "" or null.
        assert "additionalneeds" not in created["booking"]
    finally:
        client.delete(created["bookingid"], token)


def test_booking_list_has_a_stable_shape(client: BookingClient) -> None:
    ids = client.list_ids()

    assert_matches(ids, BOOKING_ID_LIST_SCHEMA)
    assert len(ids) > 0


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("firstname", "Ольга"),
        ("firstname", "O'Brien"),
        ("firstname", "a" * 100),
        ("lastname", "Иванов-Петров"),
        ("additionalneeds", "Breakfast & parking"),
        ("additionalneeds", "<script>alert(1)</script>"),
    ],
    ids=[
        "cyrillic-firstname",
        "apostrophe",
        "long-firstname",
        "hyphenated-lastname",
        "ampersand",
        "script-tag",
    ],
)
def test_awkward_values_round_trip_unchanged(
    client: BookingClient, new_booking: Booking, token: str, field: str, value: str
) -> None:
    """``parametrize`` is pytest's killer feature.

    One test body, six cases, each reported as a separate test with a readable
    id — so a failure names the case without opening the file. Jest's
    ``test.each`` is the closest equivalent; this is terser and the ``ids``
    argument gives explicit names rather than interpolated values.

    The point of these particular values: encoding and escaping bugs hide in
    apostrophes, ampersands and non-Latin text, and a value that survives ASCII
    often does not survive those.
    """
    setattr(new_booking, field, value)

    created = client.create(new_booking)

    try:
        fetched = client.get(created["bookingid"])
        assert fetched[field] == value, f"{field} was altered in transit"
    finally:
        client.delete(created["bookingid"], token)
