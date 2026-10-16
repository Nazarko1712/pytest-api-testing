"""HTTP client for the Restful Booker API.

Deliberately the same target as the Jest project
(github.com/Nazarko1712/api-testing-jest), so the two can be compared directly:
same API, same defects, different language and runner.

As there, the EXPECTED status code is a parameter rather than something a caller
branches on, so negative cases travel the same code path as positive ones.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, asdict, field
from typing import Any

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

BASE_URL = os.environ.get("API_BASE_URL", "https://restful-booker.herokuapp.com")


class UnexpectedStatus(AssertionError):
    """Raised when the API answers with a status the caller did not expect.

    Subclasses AssertionError on purpose: pytest renders it as an assertion
    failure rather than an error, which is what it is — the test's expectation
    about the API was wrong, not the test harness.
    """

    def __init__(self, method: str, path: str, expected: int, actual: int, body: str) -> None:
        super().__init__(
            f"{method} {path} -> {actual}, expected {expected}. Body: {body[:200]}"
        )
        self.expected = expected
        self.actual = actual


@dataclass
class BookingDates:
    checkin: str
    checkout: str


@dataclass
class Booking:
    firstname: str
    lastname: str
    totalprice: int
    depositpaid: bool
    bookingdates: BookingDates
    additionalneeds: str | None = field(default=None)

    def payload(self) -> dict[str, Any]:
        """Serialise, omitting an unset optional field entirely.

        Sending ``additionalneeds: null`` is NOT the same request as omitting
        it, and an API is entitled to treat them differently — so the
        distinction is preserved rather than flattened by a blanket asdict().
        """
        data = asdict(self)
        if data["additionalneeds"] is None:
            del data["additionalneeds"]
        return data


class BookingClient:
    def __init__(self, base_url: str = BASE_URL) -> None:
        self.base_url = base_url
        self.session = requests.Session()

        # Transport-level retries for genuinely transient conditions only.
        # 4xx is never retried: a 400 will still be a 400 on the third attempt,
        # and retrying it only multiplies the wasted calls.
        retry = Retry(
            total=3,
            backoff_factor=0.5,
            status_forcelist=(502, 503, 504),
            allowed_methods=("GET", "PUT", "DELETE", "POST"),
            raise_on_status=False,
        )
        self.session.mount("https://", HTTPAdapter(max_retries=retry))
        self.session.headers.update({"Accept": "application/json"})

    def _request(
        self,
        method: str,
        path: str,
        expected: int = 200,
        *,
        json: Any | None = None,
        token: str | None = None,
    ) -> requests.Response:
        headers: dict[str, str] = {}
        if json is not None:
            headers["Content-Type"] = "application/json"
        if token:
            # This API carries the token as a cookie, not a bearer header.
            headers["Cookie"] = f"token={token}"

        response = self.session.request(
            method, f"{self.base_url}{path}", json=json, headers=headers, timeout=20
        )

        if response.status_code != expected:
            raise UnexpectedStatus(method, path, expected, response.status_code, response.text)

        return response

    @staticmethod
    def _body(response: requests.Response) -> Any:
        """Decode JSON when there is JSON, fall back to text when there is not.

        Needed because this API answers 404 with a plain-text body despite the
        request asking for ``application/json``. A blind ``.json()`` therefore
        raises JSONDecodeError on a perfectly expected 404, and the failure
        reads as a client bug rather than as the API's content-type lie.

        Documented in tests/api/test_known_defects.py.
        """
        if not response.content:
            return None
        try:
            return response.json()
        except ValueError:
            return {"_raw": response.text, "_content_type": response.headers.get("Content-Type")}

    def authenticate(
        self,
        username: str | None = None,
        password: str | None = None,
        expected: int = 200,
    ) -> str:
        credentials = {
            "username": username or os.environ.get("API_USERNAME", "admin"),
            "password": password or os.environ.get("API_PASSWORD", "password123"),
        }
        return self._body(self._request("POST", "/auth", expected, json=credentials))["token"]

    def list_ids(self, expected: int = 200) -> list[dict[str, int]]:
        return self._body(self._request("GET", "/booking", expected))

    def get(self, booking_id: int | str, expected: int = 200) -> dict[str, Any]:
        return self._body(self._request("GET", f"/booking/{booking_id}", expected))

    def create(self, booking: Booking, expected: int = 200) -> dict[str, Any]:
        return self._body(self._request("POST", "/booking", expected, json=booking.payload()))

    def replace(
        self, booking_id: int, booking: Booking, token: str, expected: int = 200
    ) -> dict[str, Any]:
        return self._body(
            self._request(
                "PUT", f"/booking/{booking_id}", expected, json=booking.payload(), token=token
            )
        )

    def update(
        self, booking_id: int, changes: dict[str, Any], token: str, expected: int = 200
    ) -> dict[str, Any]:
        return self._body(
            self._request("PATCH", f"/booking/{booking_id}", expected, json=changes, token=token)
        )

    def delete(self, booking_id: int, token: str, expected: int = 201) -> requests.Response:
        """Default of 201 is not a typo.

        A successful DELETE should answer 200 or 204; this API answers 201
        ("Created") for a deletion. The client encodes the real behaviour and
        ``tests/api/test_known_defects.py`` documents why.
        """
        return self._request("DELETE", f"/booking/{booking_id}", expected, token=token)

    def filter_by_name(self, firstname: str, expected: int = 200) -> list[dict[str, int]]:
        return self._body(self._request("GET", f"/booking?firstname={firstname}", expected))
