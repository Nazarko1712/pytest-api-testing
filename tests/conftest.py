"""Shared fixtures.

``conftest.py`` is pytest's distinctive idea and the clearest difference from
Jest: fixtures are discovered by NAME and injected as arguments, rather than
imported. A test that needs a token simply declares ``token`` in its signature
and pytest resolves it, including anything that fixture itself depends on.

The practical consequences, all visible below:

  * SCOPE is explicit. A session-scoped fixture is created once for the whole
    run; a function-scoped one per test. Jest has beforeAll/beforeEach, but the
    lifetime is a property of where you wrote the hook, not of the resource.

  * Teardown lives next to setup, after ``yield``, so the cleanup for a resource
    cannot drift away from its creation.

  * Fixtures compose. ``booking`` depends on ``client``; nothing has to pass it
    down by hand.
"""

from __future__ import annotations

import random
import string
from collections.abc import Iterator
from datetime import date, timedelta
from typing import Any

import pytest
import requests

from src.client import Booking, BookingClient, BookingDates


def pytest_configure(config: pytest.Config) -> None:
    """Register markers so an unknown one is an error rather than a warning."""
    config.addinivalue_line("markers", "smoke: minimal checks that must always pass")
    config.addinivalue_line("markers", "defect: documents a known API defect")
    config.addinivalue_line("markers", "slow: makes several sequential calls")


@pytest.fixture(scope="session")
def client() -> BookingClient:
    """One HTTP client for the whole run, so the connection pool is reused."""
    return BookingClient()


@pytest.fixture(scope="session", autouse=True)
def _api_is_reachable(client: BookingClient) -> None:
    """Fail the run once if the target is down, rather than in every test.

    ``autouse`` means no test has to request it. Without this, an unreachable
    API produces thirty identical timeouts and the real cause is buried.
    """
    try:
        response = requests.get(f"{client.base_url}/ping", timeout=20)
    except requests.RequestException as error:  # pragma: no cover - environment
        pytest.exit(f"target API unreachable at {client.base_url}: {error}", returncode=3)

    if response.status_code not in (200, 201):
        pytest.exit(
            f"target API unhealthy at {client.base_url}: {response.status_code}", returncode=3
        )


@pytest.fixture(scope="session")
def token(client: BookingClient) -> str:
    """Authenticate once per session.

    Session scope on purpose: obtaining a token is not what these tests are
    about, and paying for it per test would triple the run time for no signal.
    ``tests/api/test_authorization.py`` tests the auth flow itself separately.
    """
    return client.authenticate()


def _unique_name() -> str:
    suffix = "".join(random.choices(string.ascii_lowercase + string.digits, k=10))
    return f"test{suffix}"


@pytest.fixture
def new_booking() -> Booking:
    """A realistic booking, generated fresh for each test.

    Generated rather than loaded from a fixture file: shared records are the
    first thing that makes a suite un-parallelisable, because two workers
    mutating the same row produce failures that look like product bugs.
    """
    checkin = date.today() + timedelta(days=random.randint(1, 30))
    checkout = checkin + timedelta(days=random.randint(1, 10))

    return Booking(
        firstname=_unique_name(),
        lastname="Testsson",
        totalprice=random.randint(50, 2000),
        depositpaid=random.choice([True, False]),
        bookingdates=BookingDates(checkin=checkin.isoformat(), checkout=checkout.isoformat()),
        additionalneeds=random.choice(["Breakfast", "Late checkout", "Parking"]),
    )


@pytest.fixture
def created_booking(
    client: BookingClient, token: str, new_booking: Booking
) -> Iterator[dict[str, Any]]:
    """Create a booking, hand it to the test, and remove it afterwards.

    Everything after ``yield`` runs even when the test fails, which is why
    cleanup belongs here rather than at the end of each test body.
    """
    created = client.create(new_booking)
    booking_id = created["bookingid"]

    yield {"id": booking_id, "payload": new_booking, "response": created}

    try:
        client.delete(booking_id, token)
    except AssertionError:
        # Already gone — a delete test may have removed it. Cleanup must never
        # turn a passing test into a failing one.
        pass
