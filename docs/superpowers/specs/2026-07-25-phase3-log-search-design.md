# Phase 3: Log Search — Design

Status: approved, not yet implemented.

## Goal

Replace the `app/routes/log_search_routes.py` placeholder with a real, targeted
FAZ traffic-log search tool: filter by source/destination IP (required — no
ANY/ANY, to bound query cost), optional port/service, a time window, and
optional advanced field filters; paginated results with client-side CSV/JSON
export. Ported from `ansible/faz_log_search.yml`'s filter-building logic and
`api-info/FortiAnalyzer 7.6.7 FortiAnalyzer Modules logview.json`'s documented
`/logview/adom/<adom>/logsearch` schema, not from guesswork — this replaces
the Ansible playbook's assumptions where the documented schema differs (see
"Known deviations from the Ansible playbook" below).

## Architecture

Three-layer split, following the existing `dashboard_routes.py` →
`faz_health_cache.py` → `faz_client.py` pattern:

- **`app/faz_client.py`** (extended) — add `get_log_fields(logtype)`,
  `build_filter_expression(src_clauses, dst_clauses, port_clauses,
  extra_filters)`, and `search_logs(...)`. Raw JSON-RPC only: submit (`method:
  add`) → poll (`method: get` on the returned `tid`) until
  `result.percentage == 100` or a bounded timeout → return the fetched rows.
  This is exactly what CLAUDE.md already earmarks for this file.
- **`app/log_search_filters.py`** (new) — pure, unit-testable parsing/
  validation functions for IP entries (single IP, CIDR, explicit
  `x.x.x.x-x.x.x.y` range, IPv4/IPv6, comma-separated multiples) and port/
  service entries (numeric, `tcp:443`/`udp:53`, bare service name,
  `tcp:1000-1200` range). Kept separate from `faz_client.py` because this is
  the regex/validation-heavy part needing the most test coverage, and
  isolating it keeps `faz_client.py` focused on the JSON-RPC transport +
  clause assembly, not parsing.
- **`app/routes/log_search_routes.py`** — thin HTTP layer: renders the page,
  `GET /api/log-search/targets` (allowed-ADOM-filtered target list, reusing
  `groups.get_allowed_adoms()` exactly as `dashboard_routes.py` does),
  `GET /api/log-search/fields?logtype=` (field picker data from
  `get_log_fields()`), `POST /api/log-search` (validate → build filter →
  `search_logs()` → JSON). No new persistent/stateful component — search
  is synchronous per-request (see "Execution model" below), unlike
  `faz_health_cache.py`'s background-poller pattern.
- **CSV/JSON export is client-side**, in `app/static/js/log_search.js`,
  serializing the already-fetched result set as a downloaded Blob. No export
  route — guarantees the export always matches exactly what's on screen and
  avoids a second FAZ round-trip.

## Execution model

FAZ log search is inherently async on FAZ's side (submit → poll → fetch,
same as the Ansible playbook). The app runs single-worker Gunicorn with 8
threads (`Dockerfile`), not process-based concurrency. `search_logs()` runs
the full submit→poll→fetch loop synchronously within one Flask request,
bounded by `Config.LOG_SEARCH_TIMEOUT` (default 60s), polling every
`Config.LOG_SEARCH_POLL_INTERVAL` (default 2s). This costs one of the 8
worker threads for the duration of a search; acceptable for a targeted-search
tool where the user is already waiting on the result, and avoids building a
job-tracking store. A dedicated `FAZSearchTimeout` exception (distinct from
`FAZError`) is raised if 100% isn't reached in time.

## Request/response shape

`POST /api/log-search`:

```json
{
  "target": "FortiAnalyzer Primary",
  "logtype": "traffic",
  "device": "All_FortiGate",
  "start_time": "2026-07-25T00:00:00",
  "end_time": "2026-07-25T23:59:59",
  "source_ips": ["10.1.1.0/24"],
  "destination_ips": [],
  "ports": ["tcp:443", "HTTPS"],
  "extra_filters": [{"field": "action", "op": "==", "value": "deny"}],
  "limit": 1000
}
```

- Time presets (last 15m/1h/4h/24h/7d, or Custom) are resolved to
  `start_time`/`end_time` in the browser. The backend only ever deals in
  explicit ISO start/end timestamps, matching FAZ's actual documented
  `time-range` schema (`start`/`end`, RFC 3339 or `yyyy-MM-dd HH:mm:ss`) — no
  server-side relative-window computation needed, unlike the Ansible
  playbook's `last-n-hours`/`last-n-minutes` facts (which aren't part of the
  documented API at all).
- `limit` is fixed at `Config.LOG_SEARCH_MAX_RESULTS` (default/max 1000, FAZ's
  own hard cap per the API spec) — not user-adjustable.

Response:

```json
{
  "rows": [ ... ],
  "fields": [ "itime", "srcip", "dstip", "..." ],
  "truncated": false
}
```

`truncated: true` when `return-lines == limit`, so the UI can show "hit the
result cap — narrow your filters" instead of silently looking complete.

## Backend flow

1. `@tab_required("log_search")`. Look up `target` in `faz_targets.json`;
   404 if it's not in `groups.get_allowed_adoms()` for the caller — identical
   access-control pattern to `dashboard_routes.api_dashboard()`.
2. Reject with 400 if both `source_ips` and `destination_ips` are empty (the
   no-ANY/ANY guardrail) — before any FAZ call is made.
3. `log_search_filters.py` parses/validates each IP and port/service entry
   into clause fragments. A malformed entry (bad octet, mismatched range
   order, garbage string) returns 400 naming the specific offending value —
   never silently dropped.
4. `FAZClient.build_filter_expression(...)` joins fragments with `and`,
   mirroring the Ansible Jinja template's logic (`ansible/faz_log_search.yml`,
   "Build the log filter expression" task) but in plain Python.
5. `FAZClient.search_logs(...)` submits, polls, and fetches, raising
   `FAZError` on any FAZ-reported error or `FAZSearchTimeout` if the timeout
   elapses first.
6. Route returns the JSON shape above.

## UI layout (`log_search.html`, replacing the placeholder)

- **Target** picker — dropdown, filtered by allowed ADOMs, defaults to the
  first allowed target.
- **Time range** — preset dropdown (15m/1h/4h/24h/7d/Custom); custom reveals
  start/end `datetime-local` inputs.
- **Basics** (pre-populated, always visible):
  - Source IP(s) / Destination IP(s) — comma-separated text inputs.
  - Port/Service — comma-separated text input, blank = "ANY" (allowed here
    since IP is the mandatory filter).
  - Log type — dropdown, default `traffic`.
  - Device — dropdown seeded with `All_FortiGate` plus any device-list data
    cheaply available from FAZ; falls back to a free-text field prefilled
    with `All_FortiGate` if no cheap device-list source exists (see "Open
    implementation-time checks" below).
- **Advanced filters** — "+ Add filter" button adds a row: field dropdown
  (populated from `GET /api/log-search/fields?logtype=`, backed by
  `get_log_fields()`/FAZ's `logfields` resource — the same resource
  `FAZClient.preflight()` already calls) × operator (`==`/`!=`) × value text
  input. Multiple rows allowed, each removable.
- **Results** — paginated table (client-side pagination over the single
  fetched batch, up to the 1000-row cap; no additional FAZ round-trips for
  paging within that batch). Columns are whatever fields FAZ returned.
  "Export CSV" / "Export JSON" buttons serialize the currently-loaded rows
  client-side.
- A "truncated" banner appears when the response's `truncated` flag is true.

## Filter/validation rules

**IP entries** (`log_search_filters.py`):
- Split each box on commas, trim whitespace.
- Each entry is one of: single IP (v4/v6, via `ipaddress.ip_address`), CIDR
  (`ipaddress.ip_network`), or an explicit range `x.x.x.x-x.x.x.y` (both
  sides valid IPs of the same version, start ≤ end).
- CIDR → `srcip==a.b.c.d/e` (FAZ's native syntax). Explicit range → FAZ has
  no native "between" operator for IPs, so this expands to
  `(srcip>=start and srcip<=end)`. **Not yet confirmed against a real
  appliance** — flagged as an open implementation-time check, same category
  as the Dashboard field-name/response-shape issues already found and fixed
  this session (`app/faz_client.py`'s `_unwrap_result()`,
  `app/faz_health_cache.py`'s field mapping). Verify against 192.168.64.4
  before considering range-filter support done; if the operator pairing
  doesn't work, fall back to whatever FAZ's filter grammar actually supports
  for ranges (e.g. multiple `or`'d CIDR blocks) and update this doc.
- Invalid entries → 400 naming the exact bad token.

**Port/service entries**:
- Numeric (`443`) → `dstport==443`.
- `tcp:443` / `udp:53` → `dstport==443` (protocol itself isn't filtered
  separately — inherited limitation from the Ansible playbook's own logic,
  not new scope).
- Bare word (`HTTPS`, `SSH`) → `service=="HTTPS"`, passed through as-is,
  relying on FAZ's own service-name matching.
- Range (`tcp:1000-1200`) → `(dstport>=1000 and dstport<=1200)` — extends
  past what the Ansible playbook actually implemented (it only handled
  single ports/services, no ranges), to match `plan.md`'s originally stated
  scope. Same "not yet live-validated" caveat as IP ranges above.

## Error handling

- 400 — validation failures (both IP boxes blank, malformed IP/CIDR/range,
  malformed port entry), caught before any FAZ call; message names the
  offending field/value.
- 404 — target not in the caller's allowed ADOMs.
- `FAZError` from FAZ itself (permission, bad filter syntax) — surfaced as
  FAZ's own message; these are already human-readable, unlike the raw
  urllib3 exception text fixed on the Dashboard this session.
- Network-level exceptions — reuse `_summarize_connection_error()`, moved
  from `app/faz_health_cache.py` into `app/faz_client.py` (the shared home for
  both callers), so both Dashboard and Log Search get the same clean
  "Connection refused"/"timed out" treatment instead of raw exception text.
- `FAZSearchTimeout` (poll loop exceeds `Config.LOG_SEARCH_TIMEOUT` without
  reaching 100%) — distinct message: "Search is taking too long — narrow the
  time range or add more filters."

## New Config settings

- `LOG_SEARCH_MAX_RESULTS` — fixed cap, default/max 1000 (matches FAZ's own
  documented `limit` maximum).
- `LOG_SEARCH_POLL_INTERVAL` — default 2s.
- `LOG_SEARCH_TIMEOUT` — default 60s.

Same `Config`-driven pattern as existing `FAZ_REQUEST_TIMEOUT`/`SNMP_*`
settings.

## Testing plan

- `tests/test_log_search_filters.py` — IP parsing (single/CIDR/range × v4/v6,
  invalid inputs), port/service parsing (numeric/`tcp:`/`udp:`/name/range,
  invalid inputs).
- `tests/test_faz_client.py` additions — `build_filter_expression()` clause
  assembly; `search_logs()` happy path (submit → poll(<100%) → poll(100%) →
  rows), FAZError-on-submit, timeout-without-100%, using the same
  monkeypatched-`_post` pattern as existing tests.
- `tests/test_log_search_routes.py` — 400 on both-blank IPs, 404 on
  disallowed target, happy-path JSON shape, field-picker endpoint.

## Open implementation-time checks (live validation required)

Same category as the Dashboard issues already hit and fixed this session
(field-name casing, `_unwrap_result()`'s status-field assumption) — these
must be confirmed against 192.168.64.4 during implementation, not assumed:

1. **IP/port range filter syntax** — `(srcip>=x and srcip<=y)` /
   `(dstport>=a and dstport<=b)` is a guess; confirm it's accepted by FAZ's
   filter grammar, or find the real syntax and update this doc + code
   together.
2. **Device list source** — confirm whether there's a cheap FAZ resource to
   populate a real device dropdown beyond the `All_*` wildcards; fall back to
   free-text prefilled with `All_FortiGate` if not.
3. **`/logview/adom/<adom>/logsearch` exact behavior** — the Ansible
   playbook's preflight-then-submit pattern targeted a resource path it
   wasn't fully certain of; the documented spec
   (`api-info/.../logview.json`) says `/logview/adom/<adom>/logsearch`,
   which should be used directly rather than re-deriving it, but confirm the
   full request/response shape end-to-end against the real appliance
   (required params: `url`, `apiver`, `device`, `time-range`, `logtype`).

## Documentation/help tasks (tracked as explicit plan tasks)

1. **Build out the inline help panel** — `.help-panel`/`.help-tabs`/etc. CSS
   already exists in `app/static/css/style.css` but was never wired up in
   4tlog (no template markup, no JS). Port the pattern from
   `/Users/alanw/code/github/web/4thealth` (`app/static/js/help.js` + the
   nav "?" button in `base.html`, gated by `window._helpAllowedTabs`), with
   sections for Dashboard, Log Search, and Admin, gated by
   `allowed_tabs`.
2. **Update `readme.md`** — flip Log Search from "placeholder" to shipped;
   describe the query builder/export.
3. **Update `CLAUDE.md`** — Phase 3 status; new file entries
   (`log_search_filters.py`, `faz_client.py` additions, real
   `log_search_routes.py` behavior); record the live-validation findings for
   the three open checks above once resolved.
4. **Update `ansible/readme.md`** — note the Flask app's Log Search tab now
   supersedes the playbook for this use case (playbook stays for reference,
   per existing repo conventions).

## Known deviations from the Ansible playbook

- Time range: explicit start/end only (backend), relative presets are a
  frontend convenience — not the playbook's server-side `last-n-hours` Jinja
  facts.
- Port ranges (`tcp:1000-1200`) are newly supported — the playbook's Jinja
  filter template never implemented this despite `plan.md` describing it.
- Resource path is taken directly from the documented spec
  (`/logview/adom/<adom>/logsearch`) rather than probed via
  `faz_fetch_uri_candidates`-style trial and error, since the spec already
  confirms it.
