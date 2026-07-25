# Phase 3: Log Search Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the Log Search tab placeholder with a working, targeted FortiAnalyzer traffic-log search: required source/destination IP filters (no ANY/ANY), optional port/service and advanced field filters, a time window, paginated results, and client-side CSV/JSON export.

**Architecture:** Three-layer split mirroring the existing Dashboard pattern (`dashboard_routes.py` → `faz_health_cache.py` → `faz_client.py`): `app/faz_client.py` gets new raw-JSON-RPC methods (`search_logs`, `build_filter_expression`, `get_log_fields`); a new `app/log_search_filters.py` holds pure IP/port parsing+validation; `app/routes/log_search_routes.py` stays a thin HTTP layer with no new stateful component (search is synchronous per-request). CSV/JSON export happens entirely client-side in JS.

**Tech Stack:** Flask, `requests` (existing `FAZClient`), vanilla JS (matches `dashboard.js`/`admin.js` conventions — no new frontend framework).

## Global Constraints

- No ANY/ANY searches: at least one of source IP or destination IP must be provided (400 if both blank), enforced before any FAZ call.
- Result cap fixed at `Config.LOG_SEARCH_MAX_RESULTS` (default 1000, matching FAZ's own documented `limit` maximum) — not user-adjustable.
- Search runs synchronously within one Flask request (submit → poll → fetch), bounded by `Config.LOG_SEARCH_TIMEOUT` (default 60s), polling every `Config.LOG_SEARCH_POLL_INTERVAL` (default 2s).
- Backend only accepts explicit `start_time`/`end_time`; relative time presets are resolved client-side in JS.
- Every new module follows the existing code style: no docstrings beyond a short module-level summary where non-obvious, no defensive code for scenarios that can't happen, minimal comments (only for non-obvious "why").
- Full test suite (`uv run pytest -q`) must stay green except the pre-existing, unrelated `test_config.py::test_config_requires_secret_key` failure (confirmed present on `main` before this work; do not attempt to fix it as part of this plan).
- `uv run ruff check .` must pass with no new violations.

---

### Task 1: Config settings for Log Search

**Files:**
- Modify: `app/config.py` (add new class attributes)
- Modify: `.env.example` (document new optional env vars)
- Test: `tests/test_config.py` (add assertions; do not touch the existing failing test)

**Interfaces:**
- Produces: `Config.LOG_SEARCH_MAX_RESULTS: int` (default 1000), `Config.LOG_SEARCH_POLL_INTERVAL: float` (default 2.0), `Config.LOG_SEARCH_TIMEOUT: float` (default 60.0) — consumed by Task 3 (`FAZClient.search_logs`) and Task 4 (routes).

- [x] **Step 1: Write the failing test**

Add to `tests/test_config.py`:

```python
def test_log_search_defaults(monkeypatch):
    monkeypatch.delenv("LOG_SEARCH_MAX_RESULTS", raising=False)
    monkeypatch.delenv("LOG_SEARCH_POLL_INTERVAL", raising=False)
    monkeypatch.delenv("LOG_SEARCH_TIMEOUT", raising=False)
    import importlib
    import app.config as config_mod
    importlib.reload(config_mod)
    assert config_mod.Config.LOG_SEARCH_MAX_RESULTS == 1000
    assert config_mod.Config.LOG_SEARCH_POLL_INTERVAL == 2.0
    assert config_mod.Config.LOG_SEARCH_TIMEOUT == 60.0
```

- [x] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_config.py::test_log_search_defaults -v`
Expected: FAIL with `AttributeError: type object 'Config' has no attribute 'LOG_SEARCH_MAX_RESULTS'`

- [x] **Step 3: Add the settings to `app/config.py`**

Add after the existing `# Three-tier health thresholds` block (before the `FAZ_HEALTH_POLL_DISABLED` line):

```python
    # Log Search tab (app/faz_client.py's search_logs(), app/log_search_filters.py)
    LOG_SEARCH_MAX_RESULTS = int(os.environ.get("LOG_SEARCH_MAX_RESULTS", "1000"))
    LOG_SEARCH_POLL_INTERVAL = float(os.environ.get("LOG_SEARCH_POLL_INTERVAL", "2.0"))
    LOG_SEARCH_TIMEOUT = float(os.environ.get("LOG_SEARCH_TIMEOUT", "60.0"))
```

- [x] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_config.py -v`
Expected: `test_log_search_defaults` PASSES; only the pre-existing `test_config_requires_secret_key` failure remains.

- [x] **Step 5: Document the new settings in `.env.example`**

Add after the `# Dashboard health card thresholds` block:

```bash
# Log Search tab (fixed result cap, poll timing for the submit/poll/fetch loop)
# LOG_SEARCH_MAX_RESULTS=1000
# LOG_SEARCH_POLL_INTERVAL=2.0
# LOG_SEARCH_TIMEOUT=60.0
```

- [x] **Step 6: Commit**

```bash
git add app/config.py .env.example tests/test_config.py
git commit -m "Add Log Search Config settings (max results, poll interval, timeout)"
```

---

### Task 2: `app/log_search_filters.py` — IP and port/service parsing

**Files:**
- Create: `app/log_search_filters.py`
- Test: `tests/test_log_search_filters.py`

**Interfaces:**
- Consumes: nothing (pure module, stdlib `ipaddress`/`re` only).
- Produces: `FilterValidationError(ValueError)`; `parse_ip_entries(raw: str, field: str) -> list[str]`; `parse_port_entries(raw: str) -> list[str]` — consumed by Task 4 (`log_search_routes.py`).

**Semantics to implement:**
- Split `raw` on commas, strip whitespace, ignore empty entries.
- IP entry forms: single IP (v4/v6), CIDR (`a.b.c.d/e`), or explicit range `start-end` (both sides same IP version, start ≤ end). CIDR → `{field}=={network}`. Single IP → `{field}=={addr}`. Range → `({field}>=start and {field}<=end)`.
- Port/service entry forms: bare number (`443`) → `dstport==443`; `tcp:443`/`udp:53` (protocol not separately filterable, matches inherited Ansible scope) → `dstport==443`; `tcp:1000-1200`/`udp:1000-1200` → `(dstport>=1000 and dstport<=1200)`; anything else (bare word, e.g. `HTTPS`) → `service=="HTTPS"`.
- Any malformed entry raises `FilterValidationError` naming the exact offending token.

- [x] **Step 1: Write the failing tests**

Create `tests/test_log_search_filters.py`:

```python
import pytest

from app.log_search_filters import FilterValidationError, parse_ip_entries, parse_port_entries


def test_parse_single_ipv4():
    assert parse_ip_entries("10.1.1.5", "srcip") == ["srcip==10.1.1.5"]


def test_parse_single_ipv6():
    assert parse_ip_entries("2001:db8::1", "dstip") == ["dstip==2001:db8::1"]


def test_parse_cidr():
    assert parse_ip_entries("10.1.1.0/24", "srcip") == ["srcip==10.1.1.0/24"]


def test_parse_explicit_range():
    assert parse_ip_entries("10.1.1.1-10.1.1.10", "srcip") == [
        "(srcip>=10.1.1.1 and srcip<=10.1.1.10)"
    ]


def test_parse_multiple_entries():
    result = parse_ip_entries("10.1.1.5, 10.1.2.0/24", "srcip")
    assert result == ["srcip==10.1.1.5", "srcip==10.1.2.0/24"]


def test_parse_ip_rejects_invalid_address():
    with pytest.raises(FilterValidationError, match="not-an-ip"):
        parse_ip_entries("not-an-ip", "srcip")


def test_parse_ip_rejects_mismatched_range_versions():
    with pytest.raises(FilterValidationError, match="same IP version"):
        parse_ip_entries("10.1.1.1-2001:db8::1", "srcip")


def test_parse_ip_rejects_backwards_range():
    with pytest.raises(FilterValidationError, match="greater than end"):
        parse_ip_entries("10.1.1.10-10.1.1.1", "srcip")


def test_parse_ip_empty_returns_empty_list():
    assert parse_ip_entries("", "srcip") == []


def test_parse_port_numeric():
    assert parse_port_entries("443") == ["dstport==443"]


def test_parse_port_proto_prefixed():
    assert parse_port_entries("tcp:443") == ["dstport==443"]
    assert parse_port_entries("udp:53") == ["dstport==53"]


def test_parse_port_range():
    assert parse_port_entries("tcp:1000-1200") == ["(dstport>=1000 and dstport<=1200)"]


def test_parse_port_service_name():
    assert parse_port_entries("HTTPS") == ['service=="HTTPS"']


def test_parse_port_multiple_entries():
    assert parse_port_entries("443, HTTPS") == ["dstport==443", 'service=="HTTPS"']


def test_parse_port_rejects_backwards_range():
    with pytest.raises(FilterValidationError, match="greater than end"):
        parse_port_entries("tcp:1200-1000")


def test_parse_port_empty_returns_empty_list():
    assert parse_port_entries("") == []
```

- [x] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_log_search_filters.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.log_search_filters'`

- [x] **Step 3: Implement `app/log_search_filters.py`**

```python
"""Pure parsing/validation for Log Search IP and port/service filter input.

Translates user-entered filter boxes into FortiAnalyzer filter-expression
clause fragments, ported from ansible/faz_log_search.yml's "Build the log
filter expression" Jinja task and extended to support explicit IP/port
ranges (plan.md's originally stated scope, which the playbook itself never
implemented).
"""

from __future__ import annotations

import ipaddress
import re

_PORT_RE = re.compile(r"^\d+$")
_PROTO_PORT_RE = re.compile(r"^(?:tcp|udp):(\d+)$", re.IGNORECASE)
_PROTO_RANGE_RE = re.compile(r"^(?:tcp|udp):(\d+)-(\d+)$", re.IGNORECASE)


class FilterValidationError(ValueError):
    """Raised with a message naming the exact offending input token."""


def _split_entries(raw: str) -> list[str]:
    return [entry.strip() for entry in raw.split(",") if entry.strip()]


def parse_ip_entries(raw: str, field: str) -> list[str]:
    clauses = []
    for entry in _split_entries(raw):
        if "-" in entry and "/" not in entry:
            start_str, _, end_str = entry.partition("-")
            start_str, end_str = start_str.strip(), end_str.strip()
            try:
                start = ipaddress.ip_address(start_str)
                end = ipaddress.ip_address(end_str)
            except ValueError as exc:
                raise FilterValidationError(f"Invalid IP range '{entry}': {exc}") from exc
            if start.version != end.version:
                raise FilterValidationError(
                    f"Invalid IP range '{entry}': start and end must be the same IP version"
                )
            if int(start) > int(end):
                raise FilterValidationError(
                    f"Invalid IP range '{entry}': start must not be greater than end"
                )
            clauses.append(f"({field}>={start} and {field}<={end})")
            continue
        try:
            if "/" in entry:
                network = ipaddress.ip_network(entry, strict=False)
                clauses.append(f"{field}=={network}")
            else:
                addr = ipaddress.ip_address(entry)
                clauses.append(f"{field}=={addr}")
        except ValueError as exc:
            raise FilterValidationError(f"Invalid IP/CIDR '{entry}': {exc}") from exc
    return clauses


def parse_port_entries(raw: str) -> list[str]:
    clauses = []
    for entry in _split_entries(raw):
        range_match = _PROTO_RANGE_RE.match(entry)
        if range_match:
            start, end = int(range_match.group(1)), int(range_match.group(2))
            if start > end:
                raise FilterValidationError(
                    f"Invalid port range '{entry}': start must not be greater than end"
                )
            clauses.append(f"(dstport>={start} and dstport<={end})")
            continue
        if _PORT_RE.match(entry):
            clauses.append(f"dstport=={entry}")
            continue
        proto_match = _PROTO_PORT_RE.match(entry)
        if proto_match:
            clauses.append(f"dstport=={proto_match.group(1)}")
            continue
        clauses.append(f'service=="{entry}"')
    return clauses
```

- [x] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_log_search_filters.py -v`
Expected: all PASS.

- [x] **Step 5: Lint**

Run: `uv run ruff check app/log_search_filters.py tests/test_log_search_filters.py`
Expected: no errors.

- [x] **Step 6: Commit**

```bash
git add app/log_search_filters.py tests/test_log_search_filters.py
git commit -m "Add IP/port filter parsing for Log Search"
```

---

### Task 3: `app/faz_client.py` — search_logs, build_filter_expression, get_log_fields

**Files:**
- Modify: `app/faz_client.py`
- Modify: `app/faz_health_cache.py:146-163,199` (move `_summarize_connection_error` out; update the call site and import)
- Test: `tests/test_faz_client.py` (add tests)
- Test: `tests/test_faz_health_cache.py` (update import path used by the existing network-error test, no behavior change)

**Interfaces:**
- Consumes: nothing new (stdlib `time`, existing `requests`).
- Produces:
  - `app.faz_client.FAZSearchTimeout(FAZError)` — raised by `search_logs()` when the poll loop exceeds `timeout` without reaching 100%.
  - `app.faz_client._summarize_connection_error(exc: Exception) -> str` — moved here from `app/faz_health_cache.py` (same behavior), consumed by Task 4's routes and by `faz_health_cache.py`.
  - `FAZClient.build_filter_expression(source_clauses: list[str], destination_clauses: list[str], port_clauses: list[str], extra_filters: list[dict] | None = None) -> str` (staticmethod).
  - `FAZClient.get_log_fields(logtype: str = "traffic", devtype: str = "FortiGate") -> list[dict]`.
  - `FAZClient.search_logs(logtype: str, device: str, filter_expression: str, start_time: str, end_time: str, limit: int = 1000, poll_interval: float = 2.0, timeout: float = 60.0) -> dict` returning `{"rows": [...], "fields": [...], "truncated": bool}`.
  - Consumed by: Task 4 (`log_search_routes.py`).

**Filter-assembly semantics:** multiple entries within one clause list (e.g. two source IPs) are OR'd together; the source/destination/port/extra-filter groups are AND'd against each other. Extra-filter values are unquoted if purely numeric (optionally signed), quoted otherwise.

- [x] **Step 1: Write the failing tests for `build_filter_expression`**

Add to `tests/test_faz_client.py`:

```python
def test_build_filter_expression_ors_within_group_ands_across_groups():
    from app.faz_client import FAZClient

    expr = FAZClient.build_filter_expression(
        source_clauses=["srcip==10.1.1.5", "srcip==10.1.2.0/24"],
        destination_clauses=["dstip==8.8.8.8"],
        port_clauses=["dstport==443"],
    )
    assert expr == "(srcip==10.1.1.5 or srcip==10.1.2.0/24) and (dstip==8.8.8.8) and (dstport==443)"


def test_build_filter_expression_skips_empty_groups():
    from app.faz_client import FAZClient

    expr = FAZClient.build_filter_expression(
        source_clauses=["srcip==10.1.1.5"],
        destination_clauses=[],
        port_clauses=[],
    )
    assert expr == "(srcip==10.1.1.5)"


def test_build_filter_expression_extra_filters_numeric_unquoted_string_quoted():
    from app.faz_client import FAZClient

    expr = FAZClient.build_filter_expression(
        source_clauses=["srcip==10.1.1.5"],
        destination_clauses=[],
        port_clauses=[],
        extra_filters=[
            {"field": "action", "op": "==", "value": "deny"},
            {"field": "policyid", "op": "==", "value": "5"},
        ],
    )
    assert expr == '(srcip==10.1.1.5) and action=="deny" and policyid==5'
```

- [x] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_faz_client.py -k build_filter_expression -v`
Expected: FAIL with `AttributeError: type object 'FAZClient' has no attribute 'build_filter_expression'`

- [x] **Step 3: Implement `build_filter_expression`**

In `app/faz_client.py`, add inside the `FAZClient` class (after `get_sys_status`):

```python
    @staticmethod
    def build_filter_expression(
        source_clauses: list[str],
        destination_clauses: list[str],
        port_clauses: list[str],
        extra_filters: list[dict] | None = None,
    ) -> str:
        """Combine already-parsed clause fragments (see app/log_search_filters.py)
        into one FAZ filter expression. Entries within one group are OR'd
        together; the groups themselves are AND'd against each other."""
        groups: list[str] = []
        for clause_list in (source_clauses, destination_clauses, port_clauses):
            if clause_list:
                groups.append("(" + " or ".join(clause_list) + ")")
        for f in extra_filters or []:
            value = str(f["value"])
            quoted_value = value if value.lstrip("-").isdigit() else f'"{value}"'
            groups.append(f'{f["field"]}{f["op"]}{quoted_value}')
        return " and ".join(groups)
```

- [x] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_faz_client.py -k build_filter_expression -v`
Expected: all PASS.

- [x] **Step 5: Write the failing test for `get_log_fields`**

Add to `tests/test_faz_client.py`:

```python
def test_get_log_fields_returns_field_list(monkeypatch):
    client, calls = _client(
        monkeypatch,
        [
            {
                "jsonrpc": "2.0",
                "id": 1,
                "result": {
                    "data": [
                        {
                            "index": 10,
                            "logtype": "traffic",
                            "field": [
                                {"name": "srcip", "desc": "srcip"},
                                {"name": "action", "desc": "action"},
                            ],
                        }
                    ]
                },
            }
        ],
    )
    fields = client.get_log_fields("traffic")
    assert fields == [{"name": "srcip", "desc": "srcip"}, {"name": "action", "desc": "action"}]
    assert calls[0]["json"]["params"][0]["logtype"] == "traffic"
```

- [x] **Step 6: Run test to verify it fails**

Run: `uv run pytest tests/test_faz_client.py -k get_log_fields -v`
Expected: FAIL with `AttributeError: 'FAZClient' object has no attribute 'get_log_fields'`

- [x] **Step 7: Implement `get_log_fields`**

Add to the `FAZClient` class, after `preflight()`:

```python
    def get_log_fields(self, logtype: str = "traffic", devtype: str = "FortiGate") -> list[dict]:
        """Field list for a logtype, from the same logview/logfields resource
        preflight() already probes. Confirmed live against 192.168.64.4: the
        response is a bare {"data": [{"field": [...]}]} with no "status" key
        (see _unwrap_result's handling of that)."""
        body = {
            "jsonrpc": "2.0",
            "id": self._next_id(),
            "method": "get",
            "params": [
                {
                    "url": self.preflight_resource,
                    "apiver": 3,
                    "devtype": devtype,
                    "logtype": logtype,
                }
            ],
            "session": None,
        }
        result = self._unwrap_result(self._post(body))
        data = result.get("data", [])
        if isinstance(data, list) and data and "field" in data[0]:
            return data[0]["field"]
        return []
```

- [x] **Step 8: Run test to verify it passes**

Run: `uv run pytest tests/test_faz_client.py -k get_log_fields -v`
Expected: PASS.

- [x] **Step 9: Write the failing tests for `search_logs`**

Add to `tests/test_faz_client.py`:

```python
def test_search_logs_happy_path(monkeypatch):
    client, calls = _client(
        monkeypatch,
        [
            {"jsonrpc": "2.0", "id": 1, "result": {"tid": 42}},
            {
                "jsonrpc": "2.0",
                "id": 2,
                "result": {"tid": 42, "percentage": 50, "data": []},
            },
            {
                "jsonrpc": "2.0",
                "id": 3,
                "result": {
                    "tid": 42,
                    "percentage": 100,
                    "return-lines": 2,
                    "data": [
                        {"srcip": "10.1.1.5", "dstip": "8.8.8.8"},
                        {"srcip": "10.1.1.6", "dstip": "8.8.4.4"},
                    ],
                },
            },
        ],
    )
    monkeypatch.setattr("time.sleep", lambda _s: None)
    result = client.search_logs(
        logtype="traffic",
        device="All_FortiGate",
        filter_expression="(srcip==10.1.1.0/24)",
        start_time="2026-07-25T00:00:00",
        end_time="2026-07-25T23:59:59",
        limit=1000,
        poll_interval=0.01,
        timeout=5,
    )
    assert result["rows"] == [
        {"srcip": "10.1.1.5", "dstip": "8.8.8.8"},
        {"srcip": "10.1.1.6", "dstip": "8.8.4.4"},
    ]
    assert set(result["fields"]) == {"srcip", "dstip"}
    assert result["truncated"] is False
    assert calls[0]["json"]["method"] == "add"
    assert calls[0]["json"]["params"][0]["url"] == "/logview/adom/root/logsearch"
    assert calls[0]["json"]["params"][0]["filter"] == "(srcip==10.1.1.0/24)"
    assert calls[1]["json"]["params"][0]["url"] == "/logview/adom/root/logsearch/42"


def test_search_logs_marks_truncated_when_limit_reached(monkeypatch):
    client, _ = _client(
        monkeypatch,
        [
            {"jsonrpc": "2.0", "id": 1, "result": {"tid": 7}},
            {
                "jsonrpc": "2.0",
                "id": 2,
                "result": {"tid": 7, "percentage": 100, "return-lines": 2, "data": [{}, {}]},
            },
        ],
    )
    result = client.search_logs(
        logtype="traffic", device="All_FortiGate", filter_expression="",
        start_time="2026-07-25T00:00:00", end_time="2026-07-25T23:59:59",
        limit=2, poll_interval=0.01, timeout=5,
    )
    assert result["truncated"] is True


def test_search_logs_raises_faz_error_on_submit_failure(monkeypatch):
    from app.faz_client import FAZError

    client, _ = _client(
        monkeypatch,
        [{"jsonrpc": "2.0", "id": 1, "error": {"code": -1, "message": "Bad filter"}}],
    )
    with pytest.raises(FAZError, match="Bad filter"):
        client.search_logs(
            logtype="traffic", device="All_FortiGate", filter_expression="garbage(",
            start_time="2026-07-25T00:00:00", end_time="2026-07-25T23:59:59",
        )


def test_search_logs_raises_timeout_when_never_reaches_100(monkeypatch):
    from app.faz_client import FAZSearchTimeout

    client, _ = _client(
        monkeypatch,
        [
            {"jsonrpc": "2.0", "id": 1, "result": {"tid": 1}},
            {"jsonrpc": "2.0", "id": 2, "result": {"tid": 1, "percentage": 10, "data": []}},
            {"jsonrpc": "2.0", "id": 3, "result": {"tid": 1, "percentage": 20, "data": []}},
        ],
    )
    monkeypatch.setattr("time.sleep", lambda _s: None)
    times = iter([0, 1, 2, 100])  # forces deadline exceeded on the 3rd poll
    monkeypatch.setattr("time.monotonic", lambda: next(times))
    with pytest.raises(FAZSearchTimeout):
        client.search_logs(
            logtype="traffic", device="All_FortiGate", filter_expression="",
            start_time="2026-07-25T00:00:00", end_time="2026-07-25T23:59:59",
            poll_interval=0.01, timeout=5,
        )
```

- [x] **Step 10: Run tests to verify they fail**

Run: `uv run pytest tests/test_faz_client.py -k search_logs -v`
Expected: FAIL with `AttributeError: 'FAZClient' object has no attribute 'search_logs'`

- [x] **Step 11: Implement `FAZSearchTimeout` and `search_logs`**

Add `import time` to the top of `app/faz_client.py` (alongside `import requests`).

Add after `class FAZError(Exception): ...`:

```python
class FAZSearchTimeout(FAZError):
    """Raised when a log search doesn't reach 100% within the configured timeout."""
```

Add to the `FAZClient` class, after `get_log_fields`:

```python
    def search_logs(
        self,
        logtype: str,
        device: str,
        filter_expression: str,
        start_time: str,
        end_time: str,
        limit: int = 1000,
        poll_interval: float = 2.0,
        timeout: float = 60.0,
    ) -> dict:
        """Submit a FAZ log search, poll until 100% or timeout, and return
        {"rows": [...], "fields": [...], "truncated": bool}. Ported from
        ansible/faz_log_search.yml's submit->poll->fetch loop, using the
        documented /logview/adom/<adom>/logsearch resource
        (api-info/.../logview.json) rather than the playbook's probed path."""
        submit_body = {
            "jsonrpc": "2.0",
            "id": self._next_id(),
            "method": "add",
            "params": [
                {
                    "url": f"/logview/adom/{self.adom}/logsearch",
                    "apiver": 3,
                    "device": [{"devid": device}],
                    "filter": filter_expression,
                    "limit": limit,
                    "logtype": logtype,
                    "offset": 0,
                    "case-sensitive": False,
                    "time-order": "desc",
                    "time-range": {"start": start_time, "end": end_time},
                }
            ],
            "session": None,
        }
        submit_result = self._unwrap_result(self._post(submit_body))
        tid = submit_result.get("tid")
        if tid is None:
            raise FAZError(f"Log search submit returned no task ID: {submit_result!r}")

        fetch_url = f"/logview/adom/{self.adom}/logsearch/{tid}"
        deadline = time.monotonic() + timeout
        last_result: dict = {}
        while True:
            fetch_body = {
                "jsonrpc": "2.0",
                "id": self._next_id(),
                "method": "get",
                "params": [{"url": fetch_url, "apiver": 3, "limit": limit, "offset": 0}],
                "session": None,
            }
            last_result = self._unwrap_result(self._post(fetch_body))
            if last_result.get("percentage", 0) >= 100:
                break
            if time.monotonic() >= deadline:
                raise FAZSearchTimeout(
                    f"Log search did not complete within {timeout}s "
                    f"(last percentage={last_result.get('percentage', 0)})"
                )
            time.sleep(poll_interval)

        rows = last_result.get("data", [])
        fields = sorted({key for row in rows for key in row}) if rows else []
        return_lines = last_result.get("return-lines", len(rows))
        return {
            "rows": rows,
            "fields": fields,
            "truncated": return_lines >= limit,
        }
```

- [x] **Step 12: Run tests to verify they pass**

Run: `uv run pytest tests/test_faz_client.py -v`
Expected: all PASS.

- [x] **Step 13: Move `_summarize_connection_error` into `app/faz_client.py`**

In `app/faz_health_cache.py`, delete the `_summarize_connection_error` function (currently at lines 146-163) and change line 199 from:

```python
        entry["error"] = _summarize_connection_error(exc)
```
to:
```python
        entry["error"] = summarize_connection_error(exc)
```

Update the import line (currently `from app.faz_client import FAZClient, FAZError`) to:
```python
from app.faz_client import FAZClient, FAZError, summarize_connection_error
```

Remove the now-unused `import requests` from `app/faz_health_cache.py` if nothing else in that file uses it (check with `grep -n "requests\." app/faz_health_cache.py` — if no other hits, remove the import).

Add to `app/faz_client.py`, at module level (after the `FAZSearchTimeout` class, before `class FAZClient`):

```python
def summarize_connection_error(exc: Exception) -> str:
    """Collapse a raw requests/urllib3 exception into a short, UI-friendly
    label. The full exception text still belongs in the app log."""
    if isinstance(exc, requests.exceptions.ConnectTimeout):
        return "Connection timed out"
    if isinstance(exc, requests.exceptions.SSLError):
        return "TLS/SSL error"
    if isinstance(exc, requests.exceptions.ConnectionError):
        if "Connection refused" in str(exc):
            return "Connection refused"
        if "Name or service not known" in str(exc) or "nodename nor servname" in str(exc):
            return "DNS resolution failed"
        return "Unable to connect"
    if isinstance(exc, requests.exceptions.Timeout):
        return "Request timed out"
    return "Connection failed"
```

- [x] **Step 14: Update the existing test that exercises this behavior**

In `tests/test_faz_health_cache.py`, the `test_poll_all_targets_summarizes_raw_network_error` test should still pass unchanged (it only asserts on `entry["error"]`, not on where the function lives) — no edit needed there. Add one new test to `tests/test_faz_client.py` for the moved function's direct behavior:

```python
def test_summarize_connection_error_connection_refused():
    import requests

    from app.faz_client import summarize_connection_error

    exc = requests.exceptions.ConnectionError("... Connection refused ...")
    assert summarize_connection_error(exc) == "Connection refused"
```

- [x] **Step 15: Run the full test suite**

Run: `uv run pytest -q`
Expected: only the pre-existing `test_config_requires_secret_key` failure; everything else PASSES.

- [x] **Step 16: Lint**

Run: `uv run ruff check app/faz_client.py app/faz_health_cache.py tests/test_faz_client.py`
Expected: no errors.

- [x] **Step 17: Commit**

```bash
git add app/faz_client.py app/faz_health_cache.py tests/test_faz_client.py tests/test_faz_health_cache.py
git commit -m "Add search_logs/build_filter_expression/get_log_fields to FAZClient"
```

---

### Task 4: `app/routes/log_search_routes.py` — targets, fields, and search endpoints

**Files:**
- Modify: `app/routes/log_search_routes.py` (replace placeholder route with real endpoints)
- Test: `tests/test_log_search_routes.py`

**Interfaces:**
- Consumes: `app.faz_targets.list_targets()`, `app.faz_targets.get_target(label)`, `app.groups.get_allowed_adoms(username, ad_groups, role)`, `app.decorators.check_adom_access(adom)`, `app.config.Config.{FAZ_VERIFY_SSL,FAZ_REQUEST_TIMEOUT,LOG_SEARCH_MAX_RESULTS,LOG_SEARCH_POLL_INTERVAL,LOG_SEARCH_TIMEOUT}`, `app.faz_client.{FAZClient,FAZError,FAZSearchTimeout,summarize_connection_error}`, `app.log_search_filters.{parse_ip_entries,parse_port_entries,FilterValidationError}` — all defined in prior tasks.
- Produces: `GET /api/log-search/targets`, `GET /api/log-search/fields?target=&logtype=`, `POST /api/log-search` — consumed by Task 5's frontend JS.

- [x] **Step 1: Write the failing tests**

Create `tests/test_log_search_routes.py`:

```python
import os

import pytest


@pytest.fixture
def app(tmp_path, monkeypatch):
    os.environ.setdefault("SECRET_KEY", "test-secret")
    import app.auth as auth_mod
    import app.faz_targets as faz_targets_mod
    import app.groups as groups_mod

    monkeypatch.setattr(auth_mod, "USERS_FILE", tmp_path / "users.json")
    monkeypatch.setattr(groups_mod, "GROUPS_FILE", tmp_path / "groups.json")
    monkeypatch.setattr(faz_targets_mod, "FAZ_TARGETS_FILE", tmp_path / "faz_targets.json")

    auth_mod.add_user("alice", "Str0ng!Passw0rd", role="viewer")
    groups_mod.create_group("g1", members=["alice"], allowed_tabs=["log_search"])
    faz_targets_mod.create_target("Primary", host="192.168.64.4", adom="root", token="tok")
    faz_targets_mod.create_target("Secondary", host="192.168.64.5", adom="root", token="tok2")

    from app import create_app
    return create_app()


@pytest.fixture
def client(app):
    return app.test_client()


def _login(client, username="alice", password="Str0ng!Passw0rd"):
    client.get("/login")
    with client.session_transaction() as sess:
        csrf = sess.get("_csrf_token", "")
    client.post("/login", data={"username": username, "password": password, "csrf_token": csrf})


def test_targets_requires_login(client):
    resp = client.get("/api/log-search/targets")
    assert resp.status_code == 401


def test_targets_lists_all_when_unrestricted(client):
    _login(client)
    resp = client.get("/api/log-search/targets")
    assert resp.status_code == 200
    labels = [t["label"] for t in resp.get_json()]
    assert labels == ["Primary", "Secondary"]


def test_targets_filters_by_group_restriction(client, app):
    import app.groups as groups_mod

    groups_mod.update_group(
        "g1", members=["alice"], allowed_tabs=["log_search"],
        adom_restrict=True, allowed_adoms=["Primary"],
    )
    _login(client)
    resp = client.get("/api/log-search/targets")
    labels = [t["label"] for t in resp.get_json()]
    assert labels == ["Primary"]


def test_search_rejects_both_ips_blank(client):
    _login(client)
    resp = client.post(
        "/api/log-search",
        json={
            "target": "Primary", "logtype": "traffic", "device": "All_FortiGate",
            "start_time": "2026-07-25T00:00:00", "end_time": "2026-07-25T23:59:59",
            "source_ips": "", "destination_ips": "", "ports": "",
        },
    )
    assert resp.status_code == 400
    assert "source or destination" in resp.get_json()["error"]


def test_search_rejects_invalid_ip(client):
    _login(client)
    resp = client.post(
        "/api/log-search",
        json={
            "target": "Primary", "logtype": "traffic", "device": "All_FortiGate",
            "start_time": "2026-07-25T00:00:00", "end_time": "2026-07-25T23:59:59",
            "source_ips": "not-an-ip", "destination_ips": "", "ports": "",
        },
    )
    assert resp.status_code == 400
    assert "not-an-ip" in resp.get_json()["error"]


def test_search_rejects_disallowed_target(client, app):
    import app.groups as groups_mod

    groups_mod.update_group(
        "g1", members=["alice"], allowed_tabs=["log_search"],
        adom_restrict=True, allowed_adoms=["Secondary"],
    )
    _login(client)
    resp = client.post(
        "/api/log-search",
        json={
            "target": "Primary", "logtype": "traffic", "device": "All_FortiGate",
            "start_time": "2026-07-25T00:00:00", "end_time": "2026-07-25T23:59:59",
            "source_ips": "10.1.1.5", "destination_ips": "", "ports": "",
        },
    )
    assert resp.status_code == 403


def test_search_happy_path(client, monkeypatch):
    def fake_search_logs(self, **kwargs):
        assert kwargs["filter_expression"] == "(srcip==10.1.1.5)"
        return {"rows": [{"srcip": "10.1.1.5"}], "fields": ["srcip"], "truncated": False}

    monkeypatch.setattr("app.faz_client.FAZClient.preflight", lambda self: True)
    monkeypatch.setattr("app.faz_client.FAZClient.search_logs", fake_search_logs)
    monkeypatch.setattr("app.faz_client.FAZClient.logout", lambda self: None)

    _login(client)
    resp = client.post(
        "/api/log-search",
        json={
            "target": "Primary", "logtype": "traffic", "device": "All_FortiGate",
            "start_time": "2026-07-25T00:00:00", "end_time": "2026-07-25T23:59:59",
            "source_ips": "10.1.1.5", "destination_ips": "", "ports": "",
        },
    )
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["rows"] == [{"srcip": "10.1.1.5"}]
    assert body["truncated"] is False


def test_search_returns_502_on_faz_error(client, monkeypatch):
    from app.faz_client import FAZError

    def raising_search_logs(self, **kwargs):
        raise FAZError("No permission for the resource")

    monkeypatch.setattr("app.faz_client.FAZClient.search_logs", raising_search_logs)
    monkeypatch.setattr("app.faz_client.FAZClient.logout", lambda self: None)

    _login(client)
    resp = client.post(
        "/api/log-search",
        json={
            "target": "Primary", "logtype": "traffic", "device": "All_FortiGate",
            "start_time": "2026-07-25T00:00:00", "end_time": "2026-07-25T23:59:59",
            "source_ips": "10.1.1.5", "destination_ips": "", "ports": "",
        },
    )
    assert resp.status_code == 502
    assert "No permission" in resp.get_json()["error"]


def test_search_returns_504_on_timeout(client, monkeypatch):
    from app.faz_client import FAZSearchTimeout

    def raising_search_logs(self, **kwargs):
        raise FAZSearchTimeout("did not complete")

    monkeypatch.setattr("app.faz_client.FAZClient.search_logs", raising_search_logs)
    monkeypatch.setattr("app.faz_client.FAZClient.logout", lambda self: None)

    _login(client)
    resp = client.post(
        "/api/log-search",
        json={
            "target": "Primary", "logtype": "traffic", "device": "All_FortiGate",
            "start_time": "2026-07-25T00:00:00", "end_time": "2026-07-25T23:59:59",
            "source_ips": "10.1.1.5", "destination_ips": "", "ports": "",
        },
    )
    assert resp.status_code == 504
    assert "narrow" in resp.get_json()["error"].lower()


def test_fields_endpoint(client, monkeypatch):
    monkeypatch.setattr(
        "app.faz_client.FAZClient.get_log_fields",
        lambda self, logtype="traffic", devtype="FortiGate": [{"name": "srcip"}],
    )
    monkeypatch.setattr("app.faz_client.FAZClient.logout", lambda self: None)

    _login(client)
    resp = client.get("/api/log-search/fields?target=Primary&logtype=traffic")
    assert resp.status_code == 200
    assert resp.get_json() == [{"name": "srcip"}]
```

- [x] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_log_search_routes.py -v`
Expected: FAILs (404s) since only the placeholder `GET /log-search` route currently exists.

- [x] **Step 3: Implement `app/routes/log_search_routes.py`**

Replace the entire file with:

```python
"""Log Search routes.

Page:  GET  /log-search

API (JSON):
  GET  /api/log-search/targets           allowed-ADOM-filtered target list
  GET  /api/log-search/fields?target=&logtype=   field names for the advanced-filter picker
  POST /api/log-search                   run a search, return matching rows
"""

from flask import Blueprint, jsonify, render_template, request, session

from app import registry
from app.config import Config
from app.decorators import check_adom_access, tab_required
from app.faz_client import FAZClient, FAZError, FAZSearchTimeout, summarize_connection_error
from app.faz_targets import get_target, list_targets
from app.groups import get_allowed_adoms
from app.log_search_filters import FilterValidationError, parse_ip_entries, parse_port_entries

bp = Blueprint("log_search", __name__)

registry.register("log_search", "Log Search", "log_search.index")


def _client_for(target: dict) -> FAZClient:
    return FAZClient(
        host=target["host"],
        token=target.get("token", ""),
        adom=target.get("adom", "root"),
        verify_ssl=Config.FAZ_VERIFY_SSL,
        timeout=Config.FAZ_REQUEST_TIMEOUT,
    )


@bp.route("/log-search")
@tab_required("log_search")
def index():
    return render_template("log_search.html", user=session["user"])


@bp.route("/api/log-search/targets")
@tab_required("log_search")
def api_targets():
    ad_groups = session.get("ad_groups", [])
    allowed = get_allowed_adoms(session["user"], ad_groups=ad_groups, role=session.get("role"))
    targets = list_targets()
    if allowed is not None:
        targets = [t for t in targets if t.get("label") in allowed]
    return jsonify(
        [{"label": t["label"], "host": t["host"], "adom": t.get("adom", "root")} for t in targets]
    )


@bp.route("/api/log-search/fields")
@tab_required("log_search")
def api_fields():
    target_label = request.args.get("target", "")
    err = check_adom_access(target_label)
    if err is not None:
        return err
    target = get_target(target_label)
    if target is None:
        return jsonify({"error": f"Target '{target_label}' not found"}), 404
    logtype = request.args.get("logtype", "traffic")
    try:
        with _client_for(target) as client:
            fields = client.get_log_fields(logtype)
    except FAZError as exc:
        return jsonify({"error": str(exc)}), 502
    except Exception as exc:
        return jsonify({"error": summarize_connection_error(exc)}), 502
    return jsonify(fields)


@bp.route("/api/log-search", methods=["POST"])
@tab_required("log_search")
def api_search():
    data = request.get_json(silent=True) or {}
    target_label = data.get("target", "")
    err = check_adom_access(target_label)
    if err is not None:
        return err
    target = get_target(target_label)
    if target is None:
        return jsonify({"error": f"Target '{target_label}' not found"}), 404

    source_raw = data.get("source_ips", "") or ""
    dest_raw = data.get("destination_ips", "") or ""
    if not source_raw.strip() and not dest_raw.strip():
        return jsonify({"error": "At least one of source or destination IP is required"}), 400

    start_time = data.get("start_time", "")
    end_time = data.get("end_time", "")
    if not start_time or not end_time:
        return jsonify({"error": "start_time and end_time are required"}), 400

    try:
        source_clauses = parse_ip_entries(source_raw, "srcip") if source_raw.strip() else []
        dest_clauses = parse_ip_entries(dest_raw, "dstip") if dest_raw.strip() else []
        port_clauses = parse_port_entries(data.get("ports", "") or "")
    except FilterValidationError as exc:
        return jsonify({"error": str(exc)}), 400

    filter_expression = FAZClient.build_filter_expression(
        source_clauses, dest_clauses, port_clauses, data.get("extra_filters") or []
    )

    try:
        with _client_for(target) as client:
            result = client.search_logs(
                logtype=data.get("logtype", "traffic"),
                device=data.get("device", "All_FortiGate"),
                filter_expression=filter_expression,
                start_time=start_time,
                end_time=end_time,
                limit=Config.LOG_SEARCH_MAX_RESULTS,
                poll_interval=Config.LOG_SEARCH_POLL_INTERVAL,
                timeout=Config.LOG_SEARCH_TIMEOUT,
            )
    except FAZSearchTimeout:
        return jsonify(
            {"error": "Search is taking too long — narrow the time range or add more filters."}
        ), 504
    except FAZError as exc:
        return jsonify({"error": str(exc)}), 502
    except Exception as exc:
        return jsonify({"error": summarize_connection_error(exc)}), 502

    return jsonify(result)
```

- [x] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_log_search_routes.py -v`
Expected: all PASS. (Note: `test_search_happy_path` etc. will still call the real `preflight()`/`__enter__` since only `search_logs` is monkeypatched — `preflight()` is monkeypatched too in that test to avoid a real network call; double-check any test failing with a real connection attempt has `preflight`/`logout` patched as shown above.)

- [x] **Step 5: Run the full test suite**

Run: `uv run pytest -q`
Expected: only the pre-existing `test_config_requires_secret_key` failure remains.

- [x] **Step 6: Lint**

Run: `uv run ruff check app/routes/log_search_routes.py tests/test_log_search_routes.py`
Expected: no errors.

- [x] **Step 7: Commit**

```bash
git add app/routes/log_search_routes.py tests/test_log_search_routes.py
git commit -m "Add Log Search API routes (targets, fields, search)"
```

---

### Task 5: Frontend — `log_search.html` + `log_search.js`

**Files:**
- Modify: `app/templates/log_search.html` (replace placeholder)
- Create: `app/static/js/log_search.js`
- Manual verification: no automated frontend test framework exists in this repo (matches `dashboard.js`/`admin.js`, which also have no JS unit tests) — verify by running the app and exercising the page in a browser (see Step 6).

**Interfaces:**
- Consumes: `GET /api/log-search/targets`, `GET /api/log-search/fields?target=&logtype=`, `POST /api/log-search` (Task 4). Reuses the global CSRF-injecting `window.fetch` wrapper already set up in `base.html` — no manual CSRF header handling needed in this file.
- Produces: nothing consumed by later tasks (leaf of the dependency chain).

- [x] **Step 1: Replace `app/templates/log_search.html`**

```html
{% extends "base.html" %}
{% block title %}Log Search — 4tlog{% endblock %}
{% block content %}
<div class="page-header">
  <div>
    <h2>Log Search</h2>
  </div>
</div>

<form id="searchForm" class="form-group">
  <div class="form-group">
    <label for="targetSelect">Target</label>
    <select id="targetSelect" class="form-select"></select>
  </div>

  <div class="form-group">
    <label for="timePreset">Time range</label>
    <select id="timePreset" class="form-select">
      <option value="15m">Last 15 minutes</option>
      <option value="1h" selected>Last 1 hour</option>
      <option value="4h">Last 4 hours</option>
      <option value="24h">Last 24 hours</option>
      <option value="7d">Last 7 days</option>
      <option value="custom">Custom range</option>
    </select>
  </div>
  <div class="form-group hidden" id="customTimeRow">
    <label for="startTime">Start</label>
    <input type="datetime-local" id="startTime" class="form-control" />
    <label for="endTime">End</label>
    <input type="datetime-local" id="endTime" class="form-control" />
  </div>

  <div class="form-group">
    <label for="sourceIps">Source IP(s)</label>
    <input type="text" id="sourceIps" class="form-control" placeholder="10.1.1.5, 10.1.2.0/24" />
  </div>
  <div class="form-group">
    <label for="destIps">Destination IP(s)</label>
    <input type="text" id="destIps" class="form-control" placeholder="8.8.8.8" />
  </div>
  <div class="form-group">
    <label for="ports">Port/Service</label>
    <input type="text" id="ports" class="form-control" placeholder="443, HTTPS (blank = ANY)" />
  </div>
  <div class="form-group">
    <label for="logtypeSelect">Log type</label>
    <select id="logtypeSelect" class="form-select">
      <option value="traffic" selected>traffic</option>
      <option value="event">event</option>
      <option value="virus">virus</option>
      <option value="webfilter">webfilter</option>
      <option value="app-ctrl">app-ctrl</option>
      <option value="attack">attack</option>
      <option value="dlp">dlp</option>
      <option value="emailfilter">emailfilter</option>
      <option value="voip">voip</option>
    </select>
  </div>
  <div class="form-group">
    <label for="deviceInput">Device</label>
    <input type="text" id="deviceInput" class="form-control" value="All_FortiGate" />
  </div>

  <div class="form-group">
    <label>Advanced filters</label>
    <div id="extraFilters"></div>
    <button type="button" class="btn btn-secondary btn-sm" id="addFilterBtn">+ Add filter</button>
  </div>

  <div id="searchError" class="alert alert-danger hidden"></div>

  <button type="submit" class="btn btn-primary" id="searchBtn">Search</button>
</form>

<div id="truncatedBanner" class="alert alert-warning hidden">
  Result cap reached — narrow the time range or filters to see more.
</div>

<div class="table-wrapper">
  <div class="table-controls">
    <div class="table-controls-right">
      <button class="btn btn-sm btn-secondary" id="exportCsvBtn" disabled>Export CSV</button>
      <button class="btn btn-sm btn-secondary" id="exportJsonBtn" disabled>Export JSON</button>
    </div>
  </div>
  <table class="data-table" id="resultsTable">
    <thead><tr id="resultsHeaderRow"></tr></thead>
    <tbody id="resultsBody"></tbody>
  </table>
</div>
{% endblock %}

{% block scripts %}
<script src="{{ url_for('static', filename='js/log_search.js') }}?v=1"></script>
{% endblock %}
```

- [x] **Step 2: Create `app/static/js/log_search.js`**

```javascript
'use strict';

let currentRows = [];
let currentFields = [];

function escHtml(str) {
  return String(str ?? '').replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
}

function toFazTime(date) {
  return date.toISOString().replace(/\.\d{3}Z$/, '');
}

function presetToRange(preset) {
  const end = new Date();
  const start = new Date(end);
  const match = preset.match(/^(\d+)([mhd])$/);
  if (!match) return null;
  const amount = parseInt(match[1], 10);
  if (match[2] === 'm') start.setMinutes(start.getMinutes() - amount);
  if (match[2] === 'h') start.setHours(start.getHours() - amount);
  if (match[2] === 'd') start.setDate(start.getDate() - amount);
  return { start: toFazTime(start), end: toFazTime(end) };
}

async function loadTargets() {
  const resp = await fetch('/api/log-search/targets');
  if (resp.status === 401) { location.href = '/login'; return; }
  const targets = await resp.json();
  const select = document.getElementById('targetSelect');
  select.innerHTML = targets.map((t) => `<option value="${escHtml(t.label)}">${escHtml(t.label)} (${escHtml(t.host)})</option>`).join('');
}

function addFilterRow() {
  const container = document.getElementById('extraFilters');
  const row = document.createElement('div');
  row.className = 'extra-filter-row';
  row.innerHTML = `
    <input type="text" class="form-control filter-field" placeholder="field (e.g. action)" />
    <select class="form-select filter-op">
      <option value="==">==</option>
      <option value="!=">!=</option>
    </select>
    <input type="text" class="form-control filter-value" placeholder="value" />
    <button type="button" class="btn btn-sm btn-secondary remove-filter-btn">Remove</button>
  `;
  row.querySelector('.remove-filter-btn').addEventListener('click', () => row.remove());
  container.appendChild(row);
}

function collectExtraFilters() {
  return Array.from(document.querySelectorAll('#extraFilters .extra-filter-row')).map((row) => ({
    field: row.querySelector('.filter-field').value.trim(),
    op: row.querySelector('.filter-op').value,
    value: row.querySelector('.filter-value').value.trim(),
  })).filter((f) => f.field && f.value);
}

function renderResults(result) {
  currentRows = result.rows;
  currentFields = result.fields;
  const headerRow = document.getElementById('resultsHeaderRow');
  const body = document.getElementById('resultsBody');
  headerRow.innerHTML = currentFields.map((f) => `<th>${escHtml(f)}</th>`).join('');
  body.innerHTML = currentRows.map((row) =>
    `<tr>${currentFields.map((f) => `<td>${escHtml(row[f])}</td>`).join('')}</tr>`
  ).join('');
  document.getElementById('truncatedBanner').classList.toggle('hidden', !result.truncated);
  document.getElementById('exportCsvBtn').disabled = currentRows.length === 0;
  document.getElementById('exportJsonBtn').disabled = currentRows.length === 0;
}

function downloadBlob(content, filename, mimeType) {
  const blob = new Blob([content], { type: mimeType });
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = filename;
  a.click();
  URL.revokeObjectURL(url);
}

function exportCsv() {
  const header = currentFields.join(',');
  const lines = currentRows.map((row) =>
    currentFields.map((f) => `"${String(row[f] ?? '').replace(/"/g, '""')}"`).join(',')
  );
  downloadBlob([header, ...lines].join('\n'), 'log_search_results.csv', 'text/csv');
}

function exportJson() {
  downloadBlob(JSON.stringify(currentRows, null, 2), 'log_search_results.json', 'application/json');
}

async function runSearch(e) {
  e.preventDefault();
  const errBox = document.getElementById('searchError');
  errBox.classList.add('hidden');

  const preset = document.getElementById('timePreset').value;
  let start_time, end_time;
  if (preset === 'custom') {
    start_time = document.getElementById('startTime').value;
    end_time = document.getElementById('endTime').value;
  } else {
    const range = presetToRange(preset);
    start_time = range.start;
    end_time = range.end;
  }

  const payload = {
    target: document.getElementById('targetSelect').value,
    logtype: document.getElementById('logtypeSelect').value,
    device: document.getElementById('deviceInput').value,
    start_time,
    end_time,
    source_ips: document.getElementById('sourceIps').value,
    destination_ips: document.getElementById('destIps').value,
    ports: document.getElementById('ports').value,
    extra_filters: collectExtraFilters(),
  };

  const searchBtn = document.getElementById('searchBtn');
  searchBtn.disabled = true;
  searchBtn.textContent = 'Searching…';
  try {
    const resp = await fetch('/api/log-search', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    });
    const body = await resp.json();
    if (!resp.ok) {
      errBox.textContent = body.error || 'Search failed.';
      errBox.classList.remove('hidden');
      return;
    }
    renderResults(body);
  } finally {
    searchBtn.disabled = false;
    searchBtn.textContent = 'Search';
  }
}

document.getElementById('timePreset').addEventListener('change', function () {
  document.getElementById('customTimeRow').classList.toggle('hidden', this.value !== 'custom');
});
document.getElementById('addFilterBtn').addEventListener('click', addFilterRow);
document.getElementById('searchForm').addEventListener('submit', runSearch);
document.getElementById('exportCsvBtn').addEventListener('click', exportCsv);
document.getElementById('exportJsonBtn').addEventListener('click', exportJson);

loadTargets();
```

- [x] **Step 3: Add minimal CSS for the new `.extra-filter-row` and `.hidden` utility (if not already present)**

Run: `grep -n "^\.hidden" app/static/css/style.css` — if this prints nothing, add to `app/static/css/style.css`:

```css
.hidden { display: none !important; }

.extra-filter-row {
  display: flex;
  gap: .5rem;
  margin-bottom: .5rem;
  align-items: center;
}
.extra-filter-row .form-control,
.extra-filter-row .form-select { flex: 1; }
```

(If `.hidden` already exists from the help-panel CSS in Task 6, only add `.extra-filter-row`.)

- [x] **Step 4: Start the app and verify manually in a browser**

```bash
uv run python wsgi.py
```

Log in, navigate to Log Search, and verify:
- Target dropdown populates.
- Submitting with both IP boxes blank shows the 400 error message inline.
- Submitting with a source IP populated calls `POST /api/log-search` (check Network tab) — expect a real FAZ error/timeout against the live appliance at this stage since Task 8 (live validation) hasn't run yet; this step is only confirming the UI wiring, not FAZ correctness.
- "+ Add filter" adds/removes rows correctly.
- Export buttons stay disabled until a search returns rows.

- [x] **Step 5: Lint**

Run: `uv run ruff check .` (JS isn't linted by ruff; this just re-confirms no Python regressions from earlier steps)
Expected: no errors.

- [x] **Step 6: Commit**

```bash
git add app/templates/log_search.html app/static/js/log_search.js app/static/css/style.css
git commit -m "Add Log Search UI: query builder, results table, CSV/JSON export"
```

---

### Task 6: Inline help panel (wire up existing unused CSS)

**Files:**
- Create: `app/static/js/help.js`
- Modify: `app/templates/base.html` (add help button + `window._helpAllowedTabs`/`window._helpIsAdmin` globals + script tag)
- Test: `tests/test_tab_routes.py` (add assertions that the help button renders)

**Interfaces:**
- Consumes: `allowed_tabs` and `current_role` template context vars (already injected by `app/__init__.py`'s `inject_session_globals`).
- Produces: nothing consumed by other tasks (leaf).

- [x] **Step 1: Write the failing test**

Add to `tests/test_tab_routes.py`:

```python
def test_help_button_renders_for_logged_in_user(client):
    _login(client)
    resp = client.get("/")
    assert resp.status_code == 200
    assert b'id="helpBtn"' in resp.data


def test_help_allowed_tabs_global_reflects_session(client):
    _login(client)
    resp = client.get("/")
    assert b"_helpAllowedTabs" in resp.data
    assert b"dashboard" in resp.data
```

- [x] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_tab_routes.py -k help -v`
Expected: FAIL — no `helpBtn` element exists yet.

- [x] **Step 3: Create `app/static/js/help.js`**

```javascript
'use strict';

(function () {

const SECTIONS = [
  {
    id: 'overview',
    label: 'Overview',
    html: `
<h3>What is 4tlog?</h3>
<p>4tlog is a read-only tool for monitoring and searching FortiAnalyzer appliances — no configuration changes are ever made to any device.</p>
<h3>Navigation</h3>
<ul>
  <li><strong>Dashboard</strong> — live health cards (status, version, serial, disk, CPU/mem) for each configured FortiAnalyzer appliance.</li>
  <li><strong>Log Search</strong> — targeted traffic-log search by source/destination IP, port/service, time range, and advanced fields, with CSV/JSON export.</li>
  <li><strong>Admin</strong> — manage users, groups/tab permissions, FAZ targets, and view system logs (admins only).</li>
</ul>
`,
  },
  {
    id: 'dashboard',
    label: 'Dashboard',
    tab: 'dashboard',
    html: `
<h3>Health cards</h3>
<p>Each card shows a FortiAnalyzer appliance's connectivity status, hostname, version, serial, disk usage, and (if SNMP is enabled) CPU/memory gauges. Data refreshes on a background timer — the page never blocks waiting on a live device call.</p>
<h3>Status colors</h3>
<div class="help-status-list">
  <span class="status-dot green"></span> <span><strong>Green</strong> — reachable, metrics within normal range (or SNMP disabled).</span>
  <span class="status-dot yellow"></span> <span><strong>Yellow</strong> — CPU or memory elevated (warn threshold).</span>
  <span class="status-dot red"></span> <span><strong>Red</strong> — CPU or memory critical.</span>
  <span class="status-dot gray"></span> <span><strong>Gray</strong> — first poll still pending.</span>
</div>
<p>An "offline" card with a red error message means the last poll failed — check the message for whether it's a connection issue or a permission error on the FortiAnalyzer side.</p>
`,
  },
  {
    id: 'log_search',
    label: 'Log Search',
    tab: 'log_search',
    html: `
<h3>Required filters</h3>
<p>At least one of Source IP or Destination IP must be filled in — searches with both left blank (ANY/ANY) are blocked to keep queries targeted and fast.</p>
<h3>IP formats</h3>
<p>Each IP box accepts a comma-separated list of single IPs, CIDR blocks (<code>10.1.1.0/24</code>), or explicit ranges (<code>10.1.1.1-10.1.1.10</code>) — IPv4 or IPv6.</p>
<h3>Port/Service formats</h3>
<p>Accepts a port number (<code>443</code>), <code>tcp:443</code>/<code>udp:53</code>, a range (<code>tcp:1000-1200</code>), or a bare service name (<code>HTTPS</code>). Leave blank to match any port/service.</p>
<h3>Advanced filters</h3>
<p>Use "+ Add filter" to add extra field/operator/value rows beyond the basics — narrows the search further.</p>
<h3>Export</h3>
<p>"Export CSV"/"Export JSON" download exactly the rows currently shown in the results table.</p>
`,
  },
  {
    id: 'admin',
    label: 'Admin',
    adminOnly: true,
    html: `
<h3>Groups &amp; tab permissions</h3>
<p>Groups control which tabs a user can see (<strong>allowed_tabs</strong>) and, optionally, which FortiAnalyzer targets/ADOMs they can view on the Dashboard and Log Search (<strong>adom_restrict</strong> + <strong>allowed_adoms</strong>).</p>
<h3>FAZ Targets</h3>
<p>Each target is one FortiAnalyzer appliance/ADOM: label, host, ADOM, bearer token, and optional per-target SNMP credential overrides. Edits take effect on the next poll cycle without an app restart.</p>
<h3>Logs</h3>
<p>The Logs sub-tab shows the app's own in-memory log buffer — useful for diagnosing a failed poll or search without shell access to the container.</p>
`,
  },
];

const allowed = new Set(window._helpAllowedTabs || []);
const isAdmin = Boolean(window._helpIsAdmin);

function visibleSections() {
  return SECTIONS.filter((s) => {
    if (s.adminOnly) return isAdmin;
    if (s.tab) return allowed.has(s.tab);
    return true;
  });
}

function buildPanel() {
  const sections = visibleSections();
  if (!sections.length) return;

  const tabBtns = sections.map((s, i) =>
    `<button class="help-tab${i === 0 ? ' active' : ''}" data-tab="${s.id}">${s.label}</button>`
  ).join('');
  const tabPanes = sections.map((s, i) =>
    `<div class="help-pane${i === 0 ? ' active' : ''}" id="help-pane-${s.id}">${s.html}</div>`
  ).join('');

  const panel = document.createElement('div');
  panel.id = 'helpPanel';
  panel.className = 'help-panel hidden';
  panel.setAttribute('role', 'dialog');
  panel.setAttribute('aria-modal', 'true');
  panel.setAttribute('aria-label', 'Help');
  panel.innerHTML = `
<div class="help-panel-inner">
  <div class="help-header">
    <span class="help-title">&#10067; Help &amp; Guide</span>
    <button class="help-close" id="helpClose" aria-label="Close help">&times;</button>
  </div>
  <div class="help-tabs">${tabBtns}</div>
  <div class="help-body">${tabPanes}</div>
</div>`;
  document.body.appendChild(panel);

  const backdrop = document.createElement('div');
  backdrop.id = 'helpBackdrop';
  backdrop.className = 'help-backdrop hidden';
  document.body.appendChild(backdrop);
}

function wirePanel() {
  const panel = document.getElementById('helpPanel');
  const backdrop = document.getElementById('helpBackdrop');
  const btn = document.getElementById('helpBtn');
  if (!panel) return;

  function open() {
    panel.classList.remove('hidden');
    backdrop.classList.remove('hidden');
    document.body.style.overflow = 'hidden';
  }
  function close() {
    panel.classList.add('hidden');
    backdrop.classList.add('hidden');
    document.body.style.overflow = '';
  }

  btn.addEventListener('click', open);
  document.getElementById('helpClose').addEventListener('click', close);
  backdrop.addEventListener('click', close);
  document.addEventListener('keydown', (e) => { if (e.key === 'Escape') close(); });

  panel.querySelectorAll('.help-tab').forEach((tab) => {
    tab.addEventListener('click', function () {
      panel.querySelectorAll('.help-tab').forEach((t) => t.classList.remove('active'));
      panel.querySelectorAll('.help-pane').forEach((p) => p.classList.remove('active'));
      this.classList.add('active');
      document.getElementById(`help-pane-${this.dataset.tab}`).classList.add('active');
    });
  });
}

document.addEventListener('DOMContentLoaded', () => {
  if (!document.getElementById('helpBtn')) return;
  buildPanel();
  wirePanel();
});

})();
```

- [x] **Step 4: Wire the button + globals into `app/templates/base.html`**

In the `<header class="topbar">` block, add the help button just before the existing `themeToggle` button:

```html
    <button class="btn btn-sm btn-ghost" id="helpBtn" title="Help &amp; Guide">&#10067;</button>
    <button class="btn btn-sm btn-ghost" id="themeToggle" title="Toggle light/dark mode">&#9788;</button>
```

Add the JS globals inside the existing `<script>` block's IIFE, right after `const csrfToken = ...` line:

```javascript
  window._helpAllowedTabs = {{ allowed_tabs | list | tojson }};
  window._helpIsAdmin = {{ (current_role == 'admin') | tojson }};
```

Add the `help.js` script tag right after the existing inline `<script>` block closes (before `{% block scripts %}{% endblock %}`):

```html
<script src="{{ url_for('static', filename='js/help.js') }}?v=1"></script>
```

- [x] **Step 5: Run tests to verify they pass**

Run: `uv run pytest tests/test_tab_routes.py -v`
Expected: all PASS.

- [x] **Step 6: Run the full test suite**

Run: `uv run pytest -q`
Expected: only the pre-existing `test_config_requires_secret_key` failure remains.

- [x] **Step 7: Manual verification in a browser**

```bash
uv run python wsgi.py
```

Log in, click the "?" button, confirm the panel opens with tabs matching the logged-in user's allowed tabs (Overview + Dashboard + Log Search for a viewer with both tabs granted; + Admin only when logged in as an admin). Confirm Escape and the backdrop both close it.

- [x] **Step 8: Commit**

```bash
git add app/static/js/help.js app/templates/base.html tests/test_tab_routes.py
git commit -m "Wire up the inline help panel (previously-unused CSS, now with content)"
```

---

### Task 7: Documentation updates

**Files:**
- Modify: `readme.md`
- Modify: `CLAUDE.md`
- Modify: `ansible/readme.md`

**Interfaces:** none (documentation only).

- [ ] **Step 1: Update `readme.md`**

Replace the paragraph:
```
and adds TLS for the Docker deployment (reverse-proxy container terminating
TLS in front of the app, mirroring the RHEL/Nginx setup) — see
[container.md](container.md). The Log Search tab (filtering, pagination,
export) remains a placeholder pending Phase 3.
```
with:
```
and adds TLS for the Docker deployment (reverse-proxy container terminating
TLS in front of the app, mirroring the RHEL/Nginx setup) — see
[container.md](container.md). Phase 3 makes the Log Search tab real: a
targeted FortiAnalyzer traffic-log search (required source/destination IP,
optional port/service and advanced field filters, time range) with
paginated results and client-side CSV/JSON export.
```

Replace the bullet:
```
- **Log Search Tab**: placeholder for query builder and results (Phase 3)
```
with:
```
- **Log Search Tab**: targeted FAZ log search — source/destination IP
  (required, no ANY/ANY), optional port/service and advanced field filters,
  time range (presets or custom), paginated results, CSV/JSON export of the
  currently-loaded results
- **Inline Help**: a "?" button in the nav opens a help panel with
  Dashboard/Log Search/Admin guidance, filtered to the logged-in user's
  permitted tabs
```

Replace the "Legacy Ansible scaffold" closing paragraph's forward-reference:
```
the playbook's log-search filter-building logic will be ported into
`faz_client.py`'s `search_logs()`/`build_filter_expression()` in Phase 3.
```
with:
```
the playbook's log-search filter-building logic has been ported into
`faz_client.py`'s `search_logs()`/`build_filter_expression()` as of Phase 3.
```

- [ ] **Step 2: Update `CLAUDE.md`**

In the "What this repo is" phase list, change:
```
- **Phase 3 (not started)**: the Log Search tab — query builder, filtering, pagination, CSV/JSON export. `app/routes/log_search_routes.py` currently only renders a placeholder page; `app/faz_client.py` deliberately does not yet implement `search_logs()`/`build_filter_expression()` — those are Phase 3 work, ported from the Ansible playbook's Jinja filter-building logic (see `ansible/faz_log_search.yml`'s "Build the log filter expression" task) when the Log Search tab becomes the first consumer.
```
to:
```
- **Phase 3 (shipped)**: the Log Search tab — targeted FAZ traffic-log search (required source/destination IP, optional port/service and advanced field filters, time range presets or custom), paginated results, client-side CSV/JSON export, and the previously-unused inline-help-panel CSS wired up with real content. `app/faz_client.py` implements `search_logs()`/`build_filter_expression()`/`get_log_fields()`, ported from the Ansible playbook's Jinja filter-building logic (`ansible/faz_log_search.yml`'s "Build the log filter expression" task) plus explicit IP/port range support the playbook itself never implemented despite `plan.md` describing it.
```

In the "Flask app (primary)" file list, update the `app/faz_client.py` entry's closing sentence:
```
`search_logs()`/`build_filter_expression()` are intentionally not implemented yet (Phase 3).
```
to:
```
`search_logs()`/`build_filter_expression()`/`get_log_fields()` (Phase 3) implement the log-search submit→poll→fetch loop, filter-clause assembly, and the field-picker data source respectively — see `app/log_search_filters.py` for the IP/port parsing that feeds `build_filter_expression()`. `summarize_connection_error()` (shared with `app/faz_health_cache.py`) collapses raw connection exceptions into short UI-friendly labels.
```

Add a new file entry after `app/faz_client.py`'s entry:
```
- `app/log_search_filters.py` — pure parsing/validation for Log Search's IP and port/service filter inputs (single IP, CIDR, explicit range, IPv4/IPv6; numeric/`tcp:`/`udp:`/range/bare-service-name ports), translated into FAZ filter-expression clause fragments. Kept separate from `app/faz_client.py` to isolate the regex/validation-heavy code from the JSON-RPC transport layer.
```

Update the `app/routes/log_search_routes.py` entry:
```
- `app/routes/log_search_routes.py` — `GET /log-search`, currently a placeholder page (Phase 3).
```
to:
```
- `app/routes/log_search_routes.py` — `GET /log-search` (query builder page), `GET /api/log-search/targets` (allowed-ADOM-filtered target list), `GET /api/log-search/fields?target=&logtype=` (field-picker data), `POST /api/log-search` (runs a search synchronously within the request, bounded by `Config.LOG_SEARCH_TIMEOUT`).
```

Add new file entries for the frontend:
```
- `app/static/js/log_search.js` — Log Search page behavior: target/time-preset selection, basic + advanced filter form, results table rendering, client-side CSV/JSON export of the currently-loaded rows.
- `app/static/js/help.js` — inline help panel content and open/close/tab-switch behavior, filtered to the logged-in user's `allowed_tabs` (plus an admin-only section gated on `current_role`). The `.help-panel`/`.help-tabs`/etc. CSS in `app/static/css/style.css` predates this file and was unused until Phase 3 wired it up.
```

Add a new Config bullet near the existing FAZ/SNMP Config entries in "Architecture notes" or the file list (wherever `FAZ_REQUEST_TIMEOUT`/`SNMP_*` are documented) noting:
```
`LOG_SEARCH_MAX_RESULTS`/`LOG_SEARCH_POLL_INTERVAL`/`LOG_SEARCH_TIMEOUT` (`app/config.py`) bound Log Search's synchronous submit→poll→fetch request.
```

Add to the "Reference material" section, after the existing `api-info/*.json` bullet, a note on the two live-validation checks from the design spec once resolved (fill in the actual resolution found in Task 8, replacing the bracketed placeholder text below with what was actually confirmed):
```
- Log Search's IP/port **range** filters (`(srcip>=x and srcip<=y)`, `(dstport>=a and dstport<=b)`) and the device-list source for the Log Search device picker were live-validated against 192.168.64.4 as part of Phase 3 — see `docs/superpowers/specs/2026-07-25-phase3-log-search-design.md`'s "Open implementation-time checks" section for what was confirmed/changed.
```

- [ ] **Step 3: Update `ansible/readme.md`**

Find the section describing the playbook's role relative to the Flask app (per the existing repo convention referenced in `CLAUDE.md`: "the playbook remains in the repo for reference"). Add a note near the top of that section:
```
As of Phase 3, the Flask app's Log Search tab (`/log-search`) supersedes this playbook for interactive use — it ports the same filter-building and submit/poll/fetch logic into `app/faz_client.py`/`app/log_search_filters.py` with a web UI, required source/destination IP filters, and CSV/JSON export. This playbook remains for reference and for any scripted/CLI use case outside the web app.
```

- [ ] **Step 4: Commit**

```bash
git add readme.md CLAUDE.md ansible/readme.md
git commit -m "Update docs for Phase 3 Log Search"
```

---

### Task 8: Live validation against 192.168.64.4

**Files:**
- Modify: `app/log_search_filters.py` and/or `app/faz_client.py` (only if live behavior differs from the assumptions below)
- Modify: `docs/superpowers/specs/2026-07-25-phase3-log-search-design.md` (record findings)
- Modify: `CLAUDE.md` (replace the bracketed placeholder from Task 7 Step 2 with the actual finding)
- Test: update/add tests in `tests/test_log_search_filters.py` / `tests/test_faz_client.py` if any parsing/assembly logic changes as a result

This task requires network access to the test FortiAnalyzer appliance at `192.168.64.4` (same target used throughout this repo's Phase 2 work) and a valid API token in `faz_targets.json`.

- [ ] **Step 1: Confirm the IP/port range filter operator syntax**

Using `curl` directly against the appliance (same pattern used earlier in this repo's Phase 2 debugging — see the session history / `app/faz_client.py`'s module docstring for the auth header), submit a log search with a filter string using the assumed range syntax, e.g.:

```bash
TOKEN="<token from faz_targets.json>"
curl -sk -X POST https://192.168.64.4/jsonrpc \
  -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -d '{"jsonrpc":"2.0","id":1,"method":"add","params":[{"url":"/logview/adom/root/logsearch","apiver":3,"device":[{"devid":"All_FortiGate"}],"filter":"(srcip>=10.1.1.1 and srcip<=10.1.1.10)","limit":10,"logtype":"traffic","offset":0,"case-sensitive":false,"time-order":"desc","time-range":{"start":"2026-07-24T00:00:00","end":"2026-07-25T23:59:59"}}],"session":null}' | python3 -m json.tool
```

Note the returned `tid`, then fetch it (adjust `tid` to the value returned):

```bash
curl -sk -X POST https://192.168.64.4/jsonrpc \
  -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -d '{"jsonrpc":"2.0","id":2,"method":"get","params":[{"url":"/logview/adom/root/logsearch/<tid>","apiver":3,"limit":10,"offset":0}],"session":null}' | python3 -m json.tool
```

If this returns `percentage: 100` with a non-error `status` (or no `status` key, per `_unwrap_result`'s existing handling) and rows/empty-but-valid data (not a filter-parse error), the range syntax is confirmed correct — no code changes needed. If FAZ returns a filter-parse error, try alternatives (e.g. FAZ's own range operator if one exists, or fall back to OR'd discrete values / a single CIDR covering the range) and update `parse_ip_entries`/`parse_port_entries` in `app/log_search_filters.py` accordingly, plus the corresponding unit tests.

- [ ] **Step 2: Confirm the device-list assumption**

Check whether FAZ exposes a cheap device-list resource for the target ADOM (try `/dvm/adom/root/device` or check `api-info/FortiAnalyzer 7.6.7 FortiAnalyzer Modules eventmgmt.json`/`fortiview.json` for a device-list path, since `logview.json` itself doesn't document one beyond the `All_*` enum). If a real device list is cheaply available, add a `GET /api/log-search/devices?target=` route (mirroring `api_targets`/`api_fields`) and populate `deviceInput` as a `<select>` instead of free text in `log_search.js`; if not, leave the free-text field as-is and note that decision.

- [ ] **Step 3: Confirm the full end-to-end request/response shape**

Run a full search from the actual UI (`/log-search`, logged in) against `192.168.64.4` with a real source IP known to have traffic (check `app/faz_targets.json`'s configured target or ask whoever manages the lab appliance for a known-active host), and confirm rows render correctly in the results table with sensible field names.

- [ ] **Step 4: Update the design spec with findings**

In `docs/superpowers/specs/2026-07-25-phase3-log-search-design.md`'s "Open implementation-time checks" section, replace each of the three numbered items with what was actually confirmed (syntax that worked, device-list resource found or confirmed absent, full request/response shape confirmed).

- [ ] **Step 5: Update `CLAUDE.md`'s placeholder reference note from Task 7**

Replace the bracketed reference added in Task 7 Step 2 with the concrete finding (e.g. "confirmed `(field>=x and field<=y)` works as submitted" or "range syntax required `X` instead — code updated accordingly").

- [ ] **Step 6: If code changed, run the full test suite and lint**

Run: `uv run pytest -q` — expected: only the pre-existing `test_config_requires_secret_key` failure.
Run: `uv run ruff check .` — expected: no errors.

- [ ] **Step 7: Commit**

```bash
git add docs/superpowers/specs/2026-07-25-phase3-log-search-design.md CLAUDE.md
# plus app/log_search_filters.py, app/faz_client.py, app/static/js/log_search.js,
# app/routes/log_search_routes.py, and their tests, if Steps 1-2 required code changes
git commit -m "Live-validate Log Search filter syntax and device list against 192.168.64.4"
```
