"""Defects found in the target API, asserted as they ACTUALLY behave.

Each test states the real response and carries a comment saying what the correct
one would be. The reasoning:

  * asserting the correct behaviour leaves the suite permanently red, and a
    permanently red suite stops being read
  * deleting the case loses the knowledge entirely
  * asserting reality keeps the run green, keeps the finding visible, and fails
    loudly the day the API is fixed — which is exactly when the test should be
    revisited

On a real project each of these carries a ticket reference instead of a
paragraph. The ``defect`` marker makes them selectable: ``-m defect`` to review
them, ``-m "not defect"`` to exclude them from a clean run.
"""

from __future__ import annotations

import pytest
import requests

from src.client import Booking, BookingClient, BookingDates


@pytest.mark.defect
def test_delete_answers_201_instead_of_200_or_204(
    client: BookingClient, new_booking: Booking, token: str
) -> None:
    created = client.create(new_booking)

    # Correct: 200 with no body, or 204 No Content. 201 means "Created", which
    # is the opposite of what just happened — and any client that branches on
    # the status to decide "was something created" gets it wrong.
    client.delete(created["bookingid"], token, expected=201)


@pytest.mark.defect
def test_health_endpoint_answers_201_for_a_get(client: BookingClient) -> None:
    response = requests.get(f"{client.base_url}/ping", timeout=20)

    # Correct: 200. A GET that creates nothing should not report 201.
    assert response.status_code == 201


@pytest.mark.defect
def test_failed_authentication_answers_200_with_a_reason(client: BookingClient) -> None:
    response = requests.post(
        f"{client.base_url}/auth",
        json={"username": "admin", "password": "wrong-on-purpose"},
        timeout=20,
    )
    body = response.json()

    # Correct: 401 Unauthorized. Returning 200 forces every client to parse the
    # body to discover it failed — and anything that checks only
    # `response.ok` treats a rejected login as a successful one.
    assert response.status_code == 200
    assert "token" not in body
    assert body["reason"] == "Bad credentials"


@pytest.mark.defect
def test_404_body_is_not_json_despite_the_accept_header(client: BookingClient) -> None:
    response = requests.get(
        f"{client.base_url}/booking/99999999",
        headers={"Accept": "application/json"},
        timeout=20,
    )

    assert response.status_code == 404

    # Correct: a JSON error object, since the request asked for JSON. The plain
    # text body makes a blind .json() raise JSONDecodeError on a perfectly
    # expected 404 — the failure then reads as a client bug rather than as the
    # API ignoring the Accept header. src.client._body tolerates it.
    with pytest.raises(ValueError):
        response.json()

    assert response.text.strip() != ""


@pytest.mark.defect
def test_put_with_a_partial_body_is_correctly_rejected(
    client: BookingClient, new_booking: Booking, token: str
) -> None:
    """The contrast case, included so the module is not only a list of complaints.

    PUT replaces the whole resource, so a partial body genuinely is a client
    error — and this API gets it right.
    """
    created = client.create(new_booking)

    try:
        response = requests.put(
            f"{client.base_url}/booking/{created['bookingid']}",
            json={"firstname": "OnlyThisField"},
            headers={"Content-Type": "application/json", "Cookie": f"token={token}"},
            timeout=20,
        )

        assert response.status_code == 400
    finally:
        client.delete(created["bookingid"], token)


@pytest.mark.defect
@pytest.mark.parametrize(
    "booking_id",
    ["not-a-number", "-1", "0"],
    ids=["text", "negative", "zero"],
)
def test_unparseable_ids_answer_404_rather_than_400(
    client: BookingClient, booking_id: str
) -> None:
    """Arguable rather than plainly wrong.

    400 Bad Request would describe "this is not an id" more precisely than 404
    Not Found, which claims a lookup happened. The distinction matters to a
    client deciding whether to retry. The important part is that none of these
    produce a 5xx.
    """
    response = requests.get(f"{client.base_url}/booking/{booking_id}", timeout=20)

    assert response.status_code == 404
    assert response.status_code < 500, "malformed input must never reach a 5xx"


@pytest.mark.defect
@pytest.mark.parametrize(
    "booking_id",
    ["1.5", "1.9", "01", "1abc", "1-", "1 "],
    ids=["decimal", "decimal-rounds-up", "leading-zero", "trailing-text",
         "trailing-hyphen", "trailing-space"],
)
def test_ids_with_trailing_junk_silently_resolve_to_a_real_booking(
    client: BookingClient, booking_id: str
) -> None:
    """The most interesting defect in this API, and the reason it is worth
    probing identifiers with more than one malformed value.

    Every id above returns **booking 1** with a 200. The server parses the path
    segment leniently, stopping at the first non-digit, so ``1abc``, ``1.9`` and
    ``01`` are all treated as ``1``.

    Why it matters beyond tidiness:

      * input validation upstream that rejects ``1abc`` and an API that accepts
        it disagree about what a valid identifier is, and that gap is where
        inconsistent authorisation decisions live
      * an attacker enumerating identifiers gets data back from inputs a
        developer would assume were rejected
      * ``1.9`` resolving to ``1`` rather than ``2`` is silent truncation of a
        key, which is the same class of bug as a rounded currency amount

    Correct behaviour: ``400 Bad Request`` for anything that is not a plain
    integer, or ``404`` at minimum — never a successful read of a different
    resource than the one requested.

    The canonical id is fetched first so the assertion compares against real
    data rather than a hard-coded name.
    """
    canonical = client.get(1)

    response = requests.get(
        f"{client.base_url}/booking/{booking_id}",
        headers={"Accept": "application/json"},
        timeout=20,
    )

    assert response.status_code == 200, f"expected lenient parse of {booking_id!r}"
    assert response.json() == canonical, (
        f"{booking_id!r} resolved to a booking other than 1 — the coercion rule changed"
    )
