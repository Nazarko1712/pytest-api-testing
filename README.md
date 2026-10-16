# pytest-api-testing

pytest + requests API suite against **the same target** as the
[Jest project](https://github.com/Nazarko1712/api-testing-jest) — same API, same
defects, different language and runner, so the two can be compared directly.

**40 tests, 3 modules.** Target:
[restful-booker](https://restful-booker.herokuapp.com).

## Prerequisites

| Requirement | Notes |
|---|---|
| **Python 3.10+** | `python3 --version` |
| **Network access** | `restful-booker.herokuapp.com` |
| **Nothing else** | no browser, no Docker, no database |

## Setup

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

## Running

```bash
pytest                      # all 40 tests
pytest -v                   # one line per test, with parametrize ids
pytest -n 4                 # parallel: 40 tests in ~6s instead of ~18s
pytest -m smoke             # the 3 must-always-pass checks
pytest -m "not defect"      # exclude the documented API defects
pytest -m defect            # review the defects only
pytest tests/api/test_crud.py::test_patch_changes_only_the_supplied_fields
pytest -k "coercion or token"   # select by name substring
pytest --lf                 # re-run only last failures
pytest -x                   # stop at the first failure
```

Credentials and base URL are environment-overridable:

```bash
API_BASE_URL=... API_USERNAME=... API_PASSWORD=... pytest
```

## What pytest does that Jest does not

The two suites cover the same ground, which makes the differences visible rather
than theoretical.

### Fixtures are resolved by name, not imported

```python
def test_read_returns_what_was_created(client, created_booking):
    ...
```

A test declares what it needs as an argument and pytest builds it, including
whatever that fixture itself depends on. `created_booking` depends on `client`
and `token`; nothing passes them down by hand.

**Scope is a property of the resource, not of where you wrote the hook.**
`client` and `token` are `scope="session"` — created once for the whole run.
Jest's `beforeAll` is per-file, so sharing a token across files means a module
with a mutable global.

**Teardown lives next to setup**, after `yield`, so the cleanup for a resource
cannot drift away from its creation:

```python
@pytest.fixture
def created_booking(client, token, new_booking):
    created = client.create(new_booking)
    yield {...}
    client.delete(created["bookingid"], token)   # runs even if the test fails
```

**`autouse`** lets a fixture apply without being requested — the reachability
probe runs once before anything else and no test mentions it.

### Stacked `parametrize` produces a cartesian product

```python
@pytest.mark.parametrize("bad_token", ["", "not-a-real-token", "a" * 200])
@pytest.mark.parametrize("operation", ["put", "patch", "delete"])
def test_writes_are_refused_without_a_valid_token(...)
```

Nine tests from one body, each with its own id. That is the honest way to cover
an authorization matrix — it is very easy to test the happy path of each write
and quietly never check that the other two reject a forged token.

### Markers slice the run without touching code

`smoke`, `defect` and `slow` are declared in `pytest.ini`, so `-m` expressions
select arbitrary subsets. `--strict-markers` makes a typo in
`@pytest.mark.smoek` an error rather than a silently ignored marker.

## Findings

### `1abc` returns booking 1 — with a 200

The most interesting defect here, and the reason an identifier is worth probing
with more than one malformed value.

| Request | Response |
|---|---|
| `/booking/1.5` | **200**, booking 1 |
| `/booking/1.9` | **200**, booking 1 |
| `/booking/01` | **200**, booking 1 |
| `/booking/1abc` | **200**, booking 1 |
| `/booking/-1` | 404 |
| `/booking/0` | 404 |
| `/booking/not-a-number` | 404 |

The server parses the path segment leniently, stopping at the first non-digit.
Why that matters beyond tidiness:

- upstream validation that rejects `1abc` and an API that accepts it **disagree
  about what a valid identifier is**, and that gap is where inconsistent
  authorisation decisions live
- someone enumerating identifiers gets data back from inputs a developer would
  assume were rejected
- `1.9` resolving to `1` rather than `2` is **silent truncation of a key** — the
  same class of bug as a rounded currency amount

### A 404 body is not JSON, despite `Accept: application/json`

A blind `.json()` therefore raises `JSONDecodeError` on a perfectly expected
404, and the failure reads as a client bug rather than as the API ignoring the
Accept header. `src/client.py::_body` decodes tolerantly and returns the raw
text with its content type when the body is not JSON.

### `--strict-markers` does not validate the `-m` expression

It catches a typo in a marker **applied to a test**. It does **not** catch a
typo on the command line:

```bash
$ pytest -m smoek
40 deselected in 0.03s
$ echo $?
0
```

A mistyped marker in a CI job silently runs nothing and reports success. The
guard is asserting a minimum collected count, not trusting strict-markers — the
CI workflow here does exactly that.

### Three more defects, asserted as they behave

| Defect | Actual | Correct |
|---|---|---|
| Successful DELETE | `201 Created` | `200` or `204` |
| `GET /ping` health check | `201 Created` | `200` |
| Failed authentication | `200` + `{reason}` | `401 Unauthorized` |

Asserting reality rather than correctness keeps the run green, keeps the finding
visible, and **fails loudly the day the API is fixed** — exactly when the test
should be revisited. A contrast case is included so the module is not only a
list of complaints: `PUT` with a partial body correctly answers `400`.

## Conventions

**Expected status is a parameter**, as in the Jest project:
`client.get(id)` expects 200, `client.get(id, expected=404)` expects 404. Negative
cases travel the same code path as positive ones.

**`UnexpectedStatus` subclasses `AssertionError`** so pytest renders it as an
assertion failure rather than an error. It is one: the test's expectation about
the API was wrong, not the harness.

**Transport retries only for 502/503/504.** A 400 will still be a 400 on the
third attempt, and retrying it multiplies the wasted calls.

**`filterwarnings = error`** promotes warnings to failures. A
`DeprecationWarning` from a dependency is a future breakage, and now is the
cheapest time to fix it.

**Omitted is not null.** `Booking.payload()` deletes an unset optional field
rather than serialising `None` — sending `additionalneeds: null` is a different
request from omitting it, and an API is entitled to treat them differently.
