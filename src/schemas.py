"""Contract validation with jsonschema.

Same reasoning as the Jest and Vitest projects: a value assertion answers "is
this booking's name Alice", a schema answers "is this still a booking".

The regression that reaches production is the second kind — a price arriving as
a string, an optional field becoming required, a nested object flattening. Value
assertions keep passing because the value is still present and equal after
coercion, while every consumer downstream breaks.
"""

from __future__ import annotations

from typing import Any

from jsonschema import Draft202012Validator, ValidationError

BOOKING_DATES_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "checkin": {"type": "string", "format": "date"},
        "checkout": {"type": "string", "format": "date"},
    },
    "required": ["checkin", "checkout"],
    "additionalProperties": False,
}

BOOKING_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "firstname": {"type": "string", "minLength": 1},
        "lastname": {"type": "string", "minLength": 1},
        "totalprice": {"type": "number"},
        "depositpaid": {"type": "boolean"},
        "bookingdates": BOOKING_DATES_SCHEMA,
        "additionalneeds": {"type": "string"},
    },
    "required": ["firstname", "lastname", "totalprice", "depositpaid", "bookingdates"],
    # Strict on purpose: an unannounced new field fails the test. On an API
    # holding personal data that is the behaviour you want, because a field
    # nobody mentioned is how a response starts returning more than it should.
    "additionalProperties": False,
}

CREATED_BOOKING_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "bookingid": {"type": "integer"},
        "booking": BOOKING_SCHEMA,
    },
    "required": ["bookingid", "booking"],
    "additionalProperties": False,
}

BOOKING_ID_LIST_SCHEMA: dict[str, Any] = {
    "type": "array",
    "items": {
        "type": "object",
        "properties": {"bookingid": {"type": "integer"}},
        "required": ["bookingid"],
        "additionalProperties": False,
    },
}


def assert_matches(payload: Any, schema: dict[str, Any]) -> None:
    """Validate and fail with EVERY violation, not just the first.

    ``jsonschema.validate`` stops at the first error. Collecting them all means
    a response that broke in three places is fixed in one pass instead of three
    runs — the same reason AJV is configured with ``allErrors`` in the
    JavaScript projects.
    """
    validator = Draft202012Validator(schema)
    errors: list[ValidationError] = sorted(validator.iter_errors(payload), key=lambda e: e.path)

    if errors:
        details = "\n".join(
            f"  - {'.'.join(str(p) for p in error.path) or '<root>'}: {error.message}"
            for error in errors
        )
        raise AssertionError(f"payload does not match the schema:\n{details}")
