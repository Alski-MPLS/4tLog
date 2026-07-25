# 4tlog Web App Design

Date: 2026-07-24
Status: Approved for planning

## Summary

4tlog becomes a Flask web application, structurally cloned from the `4thealth` project's
proven patterns (bcrypt auth, `groups.json` permissions, admin tab, paginated tables,
CSV/JSON/PDF export), but talking to FortiAnalyzer (FAZ) instead of FortiManager (FMG).

Three tabs:
- **Dashboard** — health cards for all configured FortiAnalyzer appliances
- **Log Search** — pre-filter → submit query → paginated results → post-filter → export
- **Admin** — users, groups & permissions, FAZ targets, log viewer

The existing Ansible playbook (`ansible/faz_log_search.yml`) is retired from the live
request path. Its proven JSON-RPC submit → poll → fetch logic, discovered resource paths,
and filter-expression building are ported directly into a new Python client
(`app/faz_client.py`), not rewritten from scratch.

## Background

The current repo (`ansible/faz_log_search.yml`, see `plan.md` and `ansible/readme.md`) is a
scaffold that proves out FAZ JSON-RPC log search: it authenticates with a bearer API key,
runs a `logview` preflight check, submits a log search (`method: add`), polls for
completion (`method: get`), and writes JSON output. It targets a test FAZ appliance at
`192.168.64.4` (FortiAnalyzer 7.4.x/7.6.x). The exact `logview` resource path and payload
shape are **not fully confirmed** — FAZ permissions and firmware version affect which
route is exposed to a given API key. This uncertainty carries forward into the web app;
see "Known risks" below.

`4thealth` (`/Users/alanw/code/github/web/4thealth`) is a mature, read-only Flask
dashboard for FortiManager/FortiGate with an established architecture this project reuses
directly: Flask app factory + blueprints, bcrypt-authenticated local accounts, group-based
tab/ADOM permission control, an admin UI for managing users/groups/targets, background
APScheduler jobs with an in-memory cache read by `/api/*` endpoints, a standard
paginated-table + full-text-filter + CSV/JSON/PDF-export UI pattern (used identically
across its Rule Review, Device Review, and Config-Diff tabs), and dual deployment paths
(Docker, and RHEL bare-metal via Gunicorn/Nginx/systemd).

## Architecture

```
4tlog/
├── app/
│   ├── __init__.py          # Flask factory, blueprints, background schedulers
│   ├── config.py            # .env -> Config
│   ├── auth.py               # bcrypt local auth (RADIUS optional, same as 4thealth)
│   ├── decorators.py         # login_required, tab_required, admin_required, check_adom_access
│   ├── registry.py           # tab registry (dashboard, log_search, admin - room for more later)
│   ├── groups.py             # group CRUD, tab + ADOM/FAZ-target access control
│   ├── faz_client.py         # NEW - JSON-RPC client for FAZ (context-manager, mirrors fmg_client.py)
│   ├── faz_health_cache.py   # NEW - background poller: SNMP CPU/mem + JSON-RPC sys status per FAZ target
│   ├── app_settings.py, api_tokens.py, atomic_io.py, app_logger.py   # reused as-is from 4thealth
│   └── routes/
│       ├── auth_routes.py, dashboard_routes.py, admin_routes.py
│       └── log_search_routes.py   # NEW - /log-search page + /api/log-search/* endpoints
├── faz_targets.json          # NEW - like infra_targets.json: [{label, host, adom, token, snmp_*}]
├── users.json, groups.json, app_settings.json   # same pattern as 4thealth (gitignored, runtime data)
├── wsgi.py, manage_users.py, Dockerfile, docker-compose.yml
└── docs/deployment.md, container.md, ...
```

## Components

### `app/faz_client.py`

Python translation of the playbook's proven logic, following the shape of 4thealth's
`fmg_client.py` (context-managed client, bearer-token auth):

- `login()` / `logout()` context manager
- `search_logs(adom, device, logtype, filter_expr, time_range, limit, offset)` — submits
  the search (`method: add`), polls (`method: get`) until `percentage == 100`, returns rows
- `build_filter_expression(source_ips, dest_ips, ports)` — same IP/port/CIDR/range/ANY and
  port-name/number/`tcp:443`/range logic as the playbook's Jinja template, translated to
  Python
- `get_sys_status(adom)` — used by the dashboard for hostname, version, serial, HA mode,
  disk usage
- Resource paths (`faz_rpc_resource`, `faz_preflight_resource`) remain configurable rather
  than hardcoded, since the exact shape is unconfirmed; the preflight-check pattern carries
  over as a startup/connection-test call

### `app/faz_health_cache.py`

Background poller mirroring `app/infra_health_cache.py` from 4thealth: SNMPv3 poll for
CPU %/memory % on each `faz_targets.json` entry (same `SNMP_ENABLED`/`SNMP_*` env vars,
`SNMP_POLL_INTERVAL` cadence), combined with JSON-RPC `sys status` for hostname, version,
serial, HA mode, and disk usage. Three-tier green/yellow/red health using the same
`CPU_WARN`/`CPU_CRIT`/`MEM_WARN`/`MEM_CRIT` threshold pattern. `/api/dashboard` reads
instantly from the cache, never blocking on a live poll.

### `faz_targets.json`

Runtime config file (gitignored, with a `faz_targets.example.json` template), parallel to
4thealth's `infra_targets.json`:

```json
[
  { "label": "FortiAnalyzer Primary", "host": "192.168.64.4", "adom": "root",
    "token": "faz-primary-bearer-token" }
]
```

Optional per-entry `snmp_user`/`snmp_auth_key`/`snmp_priv_key`/`snmp_auth_protocol`/
`snmp_priv_protocol` override the global SNMP `.env` defaults, following the same
override-over-default convention as 4thealth's `infra_targets.json`.

## Features

### Dashboard tab

One health card per `faz_targets.json` entry: label, host, ADOM, status dot
(green/yellow/red/offline), CPU %, memory %, disk usage, version, serial, HA mode/role.
Data comes from `faz_health_cache.py`, refreshed on the same interval as 4thealth's
infrastructure cache.

### Log Search tab

**Pre-filter** (sent to FAZ, shapes what's pulled):
- FAZ target + ADOM
- Log type — selectable dropdown (traffic, event, UTM, webfilter, etc.), not traffic-only
- Source IP(s) / destination IP(s) — single host, CIDR, range, or `ANY`/`ALL`; IPv4 and IPv6
- Port(s) — name (`HTTPS`), number, `tcp:443`/`udp:53`, range, or multiple entries
- Time window — relative (`30m`, `2d`) or explicit start/end date range
- Max rows

**Query flow:** submit → poll with a spinner → results land in a paginated table (10/25/50/100
rows per page, `<< < > >>` controls) — same UX as 4thealth's Rule Review policy table.

**Post-filter:** free-text/regex search box plus a field-scoped dropdown, filtering the
already-fetched result set client-side — same pattern as `hygiene.js`'s policy table filter.
Does not re-query FAZ.

**Export:** CSV, JSON, or PDF. Each export includes a filter-header block (FAZ target,
ADOM, log type, filters used, timestamp, total/filtered row counts) — the same convention
used by 4thealth's Rule Review/Device Review/Config-Diff exports.

### Admin tab

Same sub-tab structure as 4thealth:
- **Users** — local bcrypt account management (`manage_users.py` CLI + admin UI)
- **Groups & Permissions** — `allowed_tabs` (`dashboard`, `log_search`) plus
  `adom_restrict`/`allowed_adoms`, extended to also gate which `faz_targets.json` entries a
  group can see/query
- **FAZ Targets** — add/edit/remove entries in `faz_targets.json`
- **Log viewer** — in-memory ring-buffer app log, same as 4thealth's `app_logger.py`

External API and Config-Diff-style scheduled exports are explicitly **out of scope** for
v1 — not requested for this project.

## Auth & permissions

Direct reuse of 4thealth's model: `users.json` (bcrypt-hashed passwords), optional
RADIUS/AD, `groups.json` controlling both tab access and FAZ-target/ADOM access. Admins are
always unrestricted. Non-admin users see the union of allowed tabs/targets across their
groups.

## Deployment

Both paths, mirrored from 4thealth:
- **Docker** — `Dockerfile` (multi-stage, `uv sync`, non-root `appuser`) + `docker-compose.yml`
  (bind-mounted `users.json`/`groups.json`/`faz_targets.json`, HTTPS healthcheck against
  `/login`)
- **RHEL bare-metal** — `docs/deployment.md` covering Gunicorn (`--worker-class gthread`,
  required for the background health poller thread to survive), Nginx reverse proxy,
  systemd unit, firewalld/SELinux notes

## Known risks

The exact FAZ `logview` JSON-RPC resource path and payload shape are not fully confirmed
for the target account/firmware — this is an existing, documented caveat in the current
repo's `CLAUDE.md` and `ansible/readme.md`. `faz_client.py` must be validated against the
real `192.168.64.4` test appliance (and re-verified against any future production
appliance) before the Log Search tab is considered functionally complete. This is expected
first-milestone discovery work, consistent with how the original Ansible playbook was
built (preflight check + configurable resource path + documented troubleshooting steps),
not a blocker to starting implementation.

**Update (2026-07-25):** FortiAnalyzer SNMP OIDs are in fact confirmed against real
hardware (v7.4.10) in 4thealth's `infra_health_cache.py` — see
`docs/superpowers/specs/2026-07-25-phase2-dashboard-tls-design.md`. This caveat now
applies only to FortiAuthenticator OIDs, which are out of scope for 4tlog entirely
(FAZ-only project).

## Out of scope for v1

- External API (bearer-token access for other programs)
- Scheduled/recurring exports
- Multiple tabs beyond Dashboard / Log Search / Admin (registry design leaves room to add
  more later without a redesign)
