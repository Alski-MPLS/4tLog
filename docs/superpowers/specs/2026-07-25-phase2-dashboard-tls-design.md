# 4tlog Phase 2: Dashboard Tab & Docker TLS

Date: 2026-07-25
Status: Approved for planning

## Summary

Phase 2 replaces the Dashboard tab's placeholder with real FortiAnalyzer health cards,
and adds TLS termination in front of the Docker deployment. It builds the parts of
`app/faz_client.py` the Dashboard actually needs — `login()`/`logout()`, a `logview`
preflight/connectivity check, and `get_sys_status()` — and defers `search_logs()` /
`build_filter_expression()` to Phase 3, when the Log Search tab is the first consumer.
This follows directly from the Phase 1 spec
(`docs/superpowers/specs/2026-07-24-web-app-design.md`), which scoped Phase 2 as
Dashboard + Docker TLS and left the Log Search tab for Phase 3.

## Background

Phase 1 shipped the app scaffold: bcrypt auth, group-based tab permissions, an admin
shell (Users, Groups, Logs viewer), and placeholder Dashboard/Log Search tabs. The
Dashboard placeholder has no data source yet — there is no `faz_client.py`, no
`faz_targets.json`, and no health-polling cache. The Docker deployment
(`container.md`) currently serves plain HTTP only; TLS termination was explicitly
deferred to "Phase 2" in that doc.

The sibling project `/Users/alanw/code/github/web/4thealth` is a mature Flask
dashboard for FortiManager/FortiAnalyzer/FortiAuthenticator with directly-portable
patterns for both pieces of this phase:

- `app/fmg_client.py` — context-managed JSON-RPC/REST client shape to mirror for
  `faz_client.py`.
- `app/infra_health_cache.py` — a `BackgroundScheduler`-driven SNMPv3 poller feeding a
  lock-guarded in-memory cache, keyed by host, read instantly by `/api/dashboard`
  without blocking on a live device query. Its `OID_MAP["fortianalyzer"]` entry
  (`1.3.6.1.4.1.12356.103.2.1.*`, the same `fmSystem` SNMP group used by
  FortiManager) is **confirmed against real FortiAnalyzer hardware (v7.4.10)** —
  this supersedes the "FAZ SNMP OIDs are unconfirmed" caveat in the Phase 1 spec's
  "Known risks" section (see "Spec corrections" below).
- `infra_targets.json` / `infra_targets.example.json` — the target-list shape and
  optional per-entry SNMP credential override pattern that `faz_targets.json` follows.

## Spec correction (to `2026-07-24-web-app-design.md`)

That spec's "Known risks" section states FortiAnalyzer SNMP OIDs are unconfirmed.
They are in fact confirmed against real FAZ hardware in 4thealth's `infra_health_cache.py`
(v7.4.10, `fmSystem` group). This design reuses those confirmed OIDs directly rather
than re-deriving them. The remaining, still-genuinely-open risk from that section — the
exact `logview` JSON-RPC resource/payload shape for log search — is unaffected and
still applies to Phase 3, not this phase.

## Scope

**In scope:**
- `app/faz_client.py` — health/status methods only (`login`/`logout`, preflight check,
  `get_sys_status`)
- `app/faz_health_cache.py` — SNMPv3 CPU/mem polling + JSON-RPC sys status, ported from
  `infra_health_cache.py`
- `faz_targets.json` + `faz_targets.example.json`
- Admin → FAZ Targets sub-tab (CRUD UI)
- `groups.json` extended with FAZ-target visibility restriction for non-admin groups
- Dashboard tab: real health card grid, `/api/dashboard` endpoint
- Docker TLS: `nginx` reverse-proxy service in `docker-compose.yml`, cert reuse from
  `./certs/`, `container.md` updated

**Out of scope (Phase 3):**
- `search_logs()` / `build_filter_expression()` in `faz_client.py`
- Log Search tab UI, query flow, post-filter, export
- Anything the Log Search tab needs that the Dashboard doesn't

## Architecture

```
app/
├── faz_client.py          # NEW - login/logout, preflight, get_sys_status
├── faz_health_cache.py    # NEW - SNMPv3 CPU/mem + JSON-RPC sys status poller
├── routes/
│   ├── dashboard_routes.py    # real /api/dashboard + card grid (was placeholder)
│   └── admin_routes.py        # + FAZ Targets sub-tab (list/add/edit/remove)
├── templates/
│   ├── dashboard.html         # real card grid (was placeholder)
│   └── admin.html             # + FAZ Targets sub-tab panel
faz_targets.json            # NEW - gitignored runtime data
faz_targets.example.json    # NEW - committed template
docker-compose.yml           # + nginx service, app no longer publishes 8100 externally
```

## Components

### `app/faz_client.py`

Context-managed client mirroring `fmg_client.py`'s shape, authenticating with
`Authorization: Bearer <token>` (the header fix already validated against the test
appliance during the Ansible playbook debugging):

- `login()` / `logout()` — context manager over a `requests.Session`
- `preflight()` — the `logview`/`logfields` connectivity check ported from the
  playbook; used both as a startup/connection-test call and as the health cache's
  "is this target reachable" probe
- `get_sys_status(adom)` — hostname, version, serial, HA mode, disk usage
- Resource paths (`FAZ_RPC_RESOURCE`, `FAZ_PREFLIGHT_RESOURCE` env vars) stay
  configurable rather than hardcoded, per the still-open resource-path risk

`search_logs()` and `build_filter_expression()` are **not** added in this phase —
adding unused, unexercised methods ahead of their first caller violates YAGNI and
means they'd ship untested against the real appliance.

### `app/faz_health_cache.py`

Direct port of `infra_health_cache.py`, scoped to `fortianalyzer` only:

- `BackgroundScheduler` job on `SNMP_POLL_INTERVAL`, one poll cycle per
  `faz_targets.json` entry
- SNMPv3 CPU/mem via the confirmed FAZ OIDs (`1.3.6.1.4.1.12356.103.2.1.1.0` CPU,
  `.2.0`/`.3.0` mem used/total — same computed-percentage handling as FortiManager)
- Combined with `faz_client.get_sys_status()` for hostname/version/serial/HA/disk
- Three-tier health: `CPU_WARN`/`CPU_CRIT`/`MEM_WARN`/`MEM_CRIT` env-var thresholds,
  same convention as 4thealth
- `SNMP_ENABLED` defaults to `false` — CPU/mem stay blank until explicitly enabled;
  version/serial/HA/disk still populate from the JSON-RPC call regardless
- Lock-guarded in-memory dict keyed by host; `/api/dashboard` reads a snapshot,
  never blocks on a live poll or SNMP round-trip

### `faz_targets.json`

Gitignored runtime file, parallel to `infra_targets.json`:

```json
[
  { "label": "FortiAnalyzer Primary", "host": "192.168.64.4", "adom": "root",
    "token": "faz-primary-bearer-token" }
]
```

Optional per-entry `snmp_user`/`snmp_auth_key`/`snmp_priv_key`/`snmp_auth_protocol`/
`snmp_priv_protocol` override the global `SNMP_*` `.env` defaults. Ships with a
committed `faz_targets.example.json` template, following the existing
`*.example.*`-for-every-gitignored-file convention from Phase 1.

### Admin → FAZ Targets sub-tab

New sub-tab alongside the existing Users/Groups/Logs admin sub-tabs:
`admin_required`-gated list/add/edit/remove UI for `faz_targets.json` entries, using
the same atomic-write helper (`app/atomic_io.py`) the other admin CRUD screens
already use for safe concurrent writes.

### `groups.json` extension

Adds a field restricting which `faz_targets.json` entries (by `label` or `host`) a
non-admin group can see on the Dashboard, following the existing
`adom_restrict`/`allowed_adoms` shape. Admins remain unrestricted; non-admins see the
union of allowed targets across their groups — same resolution pattern
`app/groups.py` already applies to tabs and ADOMs.

## Features

### Dashboard tab

- `/api/dashboard` — returns the health cache snapshot filtered to the requesting
  user's allowed targets, reusing the groups-based filtering already established for
  tabs/ADOMs
- Card grid: one card per visible target — label, host, ADOM, status dot
  (green/yellow/red/offline), CPU%, mem%, disk usage, version, serial, HA mode — same
  visual pattern as 4thealth's dashboard cards
- Client-side JS polls `/api/dashboard` on an interval (mirrors 4thealth's dashboard
  JS), no full page reload
- An unreachable/offline target renders a distinct grey/red state instead of blank
  fields, so a down appliance is visually obvious rather than looking broken

### Docker TLS

- New `nginx` service in `docker-compose.yml`, terminating TLS on the externally
  published port and proxying plain HTTP to `app:8100` over the internal Docker
  network — same directive shape as the Nginx block already documented in
  `docs/deployment.md` §3/§5 for the RHEL path, just `proxy_pass http://app:8100`
  instead of `127.0.0.1:8100`
- Bind-mounts the same `./certs/cert.pem` + `./certs/key.pem` the Flask app already
  optionally uses in dev — one cert location, one `cp certs.example → certs` flow,
  documented in `container.md`
- `app` service stops publishing `8100` externally once nginx fronts it
- `.env` gets `COOKIE_SECURE=true` and `TRUSTED_PROXY_COUNT=1` for this topology, per
  the reasoning already written up in `docs/deployment.md` §5 for the equivalent
  RHEL/Nginx setup
- `container.md`'s "Planned (Phase 2)" section is rewritten to describe the shipped
  setup instead of the plan

## Testing / validation

- Unit tests for `faz_client.py` methods against a mocked `requests.Session`
  (matches the existing test style in `tests/`)
- Unit tests for `faz_health_cache.py`'s threshold/status-tier logic and cache
  read/write, with SNMP calls mocked
- Admin FAZ Targets CRUD covered by route tests, same pattern as the existing admin
  route tests (`tests/test_admin_routes.py`)
- **Live validation against the real test appliance** (`192.168.64.4`), not just
  mocks, before Phase 2 is considered complete:
  - `faz_client.get_sys_status()` exercised live, following the same
    curl-then-playbook verification approach used to find and fix the Ansible
    `Authorization: Bearer` auth bug
  - If `SNMP_ENABLED=true` is exercised, spot-check the confirmed FAZ OIDs with
    `snmpwalk` against the test appliance
  - `docker compose up` end-to-end smoke test: TLS terminates at nginx, the
    dashboard loads over HTTPS, an admin can add/edit a FAZ target via the new UI
    and see it reflected on the dashboard

## Known risks

- The exact `logview` JSON-RPC resource/payload shape remains unconfirmed for
  arbitrary accounts/firmware (per the Phase 1 spec) — this affects Phase 3's log
  search, not this phase's `get_sys_status()`/preflight calls, but should be kept in
  mind if a different FAZ account/firmware is targeted later.
- FortiAuthenticator SNMP OIDs are still unconfirmed in 4thealth — not applicable to
  this phase (FAZ-only), noted here only so it isn't confused with the now-resolved
  FAZ OID risk.

## Out of scope for Phase 2

- Log Search tab and everything it needs in `faz_client.py`
- External API (bearer-token access for other programs) — out of scope for v1 per
  the Phase 1 spec
- Scheduled/recurring exports — same
