# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this repo is

4tLog is a Flask web application for interacting with Fortinet FortiAnalyzer (FAZ) over its JSON-RPC API. The end goal (see [plan.md](plan.md)) is to let a user query FAZ traffic logs by source/destination IP, port, and time window, with human-readable output exportable to CSV/JSON.

The app is being built in phases:

- **Phase 1 (shipped)**: Flask app skeleton — bcrypt local auth, session security (CSRF, absolute session lifetime, security headers), group-based access control (per-group tab permissions and ADOM/target restriction), and an Admin tab for managing users/groups/logs.
- **Phase 2 (shipped)**: a real Dashboard tab — FAZ health cards backed by a background poller (`app/faz_health_cache.py`) that calls `app/faz_client.py` for status and (optionally) SNMPv3 for CPU/mem — plus an Admin → FAZ Targets CRUD sub-tab to manage which FAZ appliances are polled, and Docker TLS (an Nginx reverse-proxy container terminating TLS in front of the app).
- **Phase 3 (not started)**: the Log Search tab — query builder, filtering, pagination, CSV/JSON export. `app/routes/log_search_routes.py` currently only renders a placeholder page; `app/faz_client.py` deliberately does not yet implement `search_logs()`/`build_filter_expression()` — those are Phase 3 work, ported from the Ansible playbook's Jinja filter-building logic (see `ansible/faz_log_search.yml`'s "Build the log filter expression" task) when the Log Search tab becomes the first consumer.

The original Ansible playbook (`ansible/faz_log_search.yml`) predates the Flask app and was the initial scaffold for discovering FAZ's log-search endpoint/permission shape. It still exists and still works, but it is now a **secondary/legacy path** — the Flask app is the primary interface going forward. See [ansible/readme.md](ansible/readme.md) for the playbook's own behavior/variables/troubleshooting.

## Repository layout

### Flask app (primary)

- `app/__init__.py` — `create_app()` factory. Registers blueprints (from `_BLUEPRINT_MODULES`), CSRF/security-header hooks (`app.security`), the `groups.KNOWN_TABS` sync from the tab registry, and starts the FAZ health background poller (`app.faz_health_cache.init_scheduler`) unless `Config.FAZ_HEALTH_POLL_DISABLED`.
- `app/config.py` — `Config` class loaded from environment/`.env` (via `python-dotenv`). Requires a real `SECRET_KEY` (raises at import time otherwise — generate one with `uv run python manage_users.py secret`). Holds FAZ client settings (`FAZ_VERIFY_SSL`, `FAZ_REQUEST_TIMEOUT`), SNMPv3 polling settings (`SNMP_*`), and CPU/mem health thresholds (`CPU_WARN`/`CPU_CRIT`/`MEM_WARN`/`MEM_CRIT`).
- `app/auth.py` — bcrypt-backed local user store (`users.json`), login/session helpers. Accounts are managed via the `manage_users.py` CLI, not through the UI.
- `app/groups.py` — group store (`groups.json`): per-group `members`, `ad_groups` (reserved for future RADIUS/AD), `allowed_tabs`, and `adom_restrict`/`allowed_adoms` for FAZ-target access control. `get_allowed_tabs()`/`get_allowed_adoms()` are consumed by `app/decorators.py` and `app/routes/dashboard_routes.py` respectively — admins are always unrestricted.
- `app/registry.py` — central tab registry; each blueprint module calls `registry.register(key, display_name, endpoint)` at import time so nav links and admin's tab-permission picker stay in sync automatically.
- `app/decorators.py` — `@tab_required(key)` (session + group tab-permission check) and `@admin_required` (role check) route decorators.
- `app/security.py` — CSRF token issuance/validation used by `app/__init__.py`'s `before_request` hook.
- `app/app_logger.py` — in-memory ring-buffer app logger surfaced via Admin → Logs (`/admin/api/logs`).
- `app/faz_client.py` — `FAZClient`, a read-only JSON-RPC client for FAZ health/status calls only (`preflight()`, `get_sys_status()`). Authenticates with `Authorization: Bearer <token>` — confirmed against the test appliance that `X-API-Key` and no-auth-header both silently produce a `-11 No permission` error while `Authorization: Bearer` returns real data. `search_logs()`/`build_filter_expression()` are intentionally not implemented yet (Phase 3).
- `app/faz_targets.py` — CRUD over `faz_targets.json` (a JSON array, not a dict, matching 4thealth's `infra_targets.json` convention). Each entry: `label` (unique key), `host`, `adom`, `token`, plus optional per-target SNMP credential overrides (`snmp_user`, `snmp_auth_key`, `snmp_priv_key`, `snmp_auth_protocol`, `snmp_priv_protocol`) that fall back to the matching `Config.SNMP_*` default when absent. Re-reads the file on every call (no in-memory cache) so admin edits are picked up by the next poll cycle without an app restart. See `faz_targets.example.json` for the shape.
- `app/faz_health_cache.py` — background poller. Every `Config.SNMP_POLL_INTERVAL` seconds (via APScheduler, started by `init_scheduler()`), for every `faz_targets.py` entry: calls `FAZClient.preflight()` + `get_sys_status()`, and — if `Config.SNMP_ENABLED` — an SNMPv3 `GET` against FortiAnalyzer's `fmSystem` OID group (`1.3.6.1.4.1.12356.103.2.1.*`, ported from `4thealth`'s `infra_health_cache.py`) for CPU/mem-used/mem-total. Results land in a lock-guarded in-memory dict; `get_all_cached()` returns a snapshot (never blocks on a live poll) with a `red`/`yellow`/`green`/`gray`/`offline` `status` classification per target. `poll_now()` triggers an immediate out-of-band poll in a daemon thread. Disabled entirely under test via `Config.FAZ_HEALTH_POLL_DISABLED` (set by `tests/conftest.py`).
- `app/routes/auth_routes.py` — login/logout.
- `app/routes/dashboard_routes.py` — `GET /` (Dashboard page) and `GET /api/dashboard` (JSON list of health cards from `faz_health_cache.get_all_cached()`, filtered by `groups.get_allowed_adoms()` for the current session's group memberships — non-admin users with `adom_restrict=True` on all their groups only see cards for their `allowed_adoms`).
- `app/routes/admin_routes.py` — `GET /admin` (page) plus JSON APIs: `/admin/api/groups` (CRUD), `/admin/api/faz-targets` (CRUD, backed by `app/faz_targets.py`), `/admin/api/users` (read-only list for the group member picker), `/admin/api/tabs` (tab registry), `/admin/api/logs` (view/filter/clear the app log buffer, change log level).
- `app/routes/log_search_routes.py` — `GET /log-search`, currently a placeholder page (Phase 3).
- `app/static/js/dashboard.js` — polls `/api/dashboard` and renders one health card per target (`renderCard()`): status color, hostname/version/serial/HA mode/HA role/disk usage, CPU/mem gauges (or an SNMP-disabled/error state), last-updated timestamp.
- `app/static/js/admin.js` — admin page behavior: groups CRUD (including the `adom_restrict`/`allowed_adoms` fields), FAZ Targets CRUD sub-tab, users list, tabs picker, live log viewer.
- `app/templates/` — `base.html` (nav shell, driven by `registry`/`allowed_tabs`), `login.html`, `dashboard.html`, `admin.html`, `log_search.html`.
- `manage_users.py` — CLI for creating/managing local accounts (`add`, `secret` to generate a `SECRET_KEY`, etc.) — the only supported way to create users; there is no signup UI.
- `wsgi.py` — entrypoint (`uv run python wsgi.py`); serves HTTPS directly if `certs/cert.pem`/`certs/key.pem` are present, otherwise plain HTTP on `PORT` (default `5443`).
- `users.json` / `groups.json` / `faz_targets.json` — local JSON stores (gitignored; seed from the matching `*.example.json` files). Bind-mounted into the Docker container so admin edits persist across restarts.
- `tests/` — pytest suite covering auth, decorators, groups, registry, security, app_logger, `faz_client`, `faz_health_cache`, `faz_targets`, and each route module. `tests/conftest.py` sets `FAZ_HEALTH_POLL_DISABLED=true` so the suite never starts real background network/SNMP threads.

### Docker / TLS deployment

- `Dockerfile`, `docker-compose.yml` — two services: `app` (this Flask app under Gunicorn, `expose`s `8100` internally only — no host port) and `nginx` (an `nginx:1.27-alpine` reverse proxy that terminates TLS and publishes `8443`→443 and `8080`→80 to the host). `nginx/nginx.conf` proxies plaintext HTTP to `app:8100` over the internal Docker network.
- `certs/` (gitignored) — `cert.pem`/`key.pem` read by the `nginx` service; see [container.md](container.md) for generating a self-signed pair for local/dev use.
- Because TLS terminates at `nginx`, not `app`, set `COOKIE_SECURE=true` and `TRUSTED_PROXY_COUNT=1` in `.env` for the Docker path — `Config`'s `COOKIE_SECURE=auto` detection only looks for certs on `app`'s own filesystem, which this topology never has. See [container.md](container.md) for the full quick-start sequence and [docs/deployment.md](docs/deployment.md) for the RHEL/Gunicorn/Nginx/systemd bare-metal alternative (same TLS-not-at-the-app reasoning, §5).

### Reference material

- `api-info/*.json` — official FortiAnalyzer 7.6.7 Swagger/OpenAPI specs for the `eventmgmt`, `fortiview`, and `logview` modules. Authoritative reference for available JSON-RPC resources/parameters/response schemas — consult before guessing at an API shape. Note `get_sys_status()`'s `/sys/status` resource is *not* covered by these specs (only logview/eventmgmt/fortiview are) — its response field names (`hostname`, `version`, `serial`, `ha-mode`/`ha_mode`, `ha-role`/`ha_role`, `disk-usage`/`disk_usage`) are still only validated against `tests/test_faz_client.py`'s mocks, **not** against a real appliance response. Live validation against `192.168.64.4` (a real API token and network reachability required) is outstanding — see Task 9 in `docs/superpowers/plans/2026-07-25-phase2-dashboard-tls.md`. If the real field names differ, update `app/faz_health_cache.py`'s `_poll_target()` lookups and the corresponding mocked test data together.
- `api-info/site.md` — short primer on the FAZ JSON-RPC message format (request/response envelope: `id`, `method`, `params`, `session`; response `status.code` of `0` means success).

## Running the app

```bash
uv sync
cp .env.example .env               # set SECRET_KEY (uv run python manage_users.py secret)
cp users.example.json users.json
cp groups.example.json groups.json
cp faz_targets.example.json faz_targets.json   # optional — seeds the Dashboard's poll list
uv run python manage_users.py add admin --role admin
uv run python wsgi.py              # http://localhost:5443 (PORT env var overrides; add certs/ for HTTPS)
```

Test suite / lint:

```bash
uv run pytest -q
uv run ruff check .
```

Test FAZ appliance: `192.168.64.4` (test creds live outside this repo — do not hardcode them anywhere, and never commit a real bearer token into `faz_targets.json` or `.env`).

## Running the legacy Ansible playbook

```bash
ansible-playbook ansible/faz_log_search.yml --extra-vars 'faz_api_key=YOUR_API_KEY'
```

Prefer the vaulted credentials file over passing the key on the command line:

```bash
ansible-playbook ansible/faz_log_search.yml -e @ansible/my-vault.yml --ask-vault-pass
```

Key overridable variables (via `--extra-vars`): `faz_host`, `faz_port`, `faz_adom`, `faz_rpc_resource`, `faz_fetch_uri_candidates`, `faz_source_ips`, `faz_destination_ips`, `faz_ports`, `faz_time_window`, `faz_start_time`/`faz_end_time`, `faz_max_logs`, `faz_output_format`. When passing lists/objects, use JSON syntax for `--extra-vars` (a single JSON blob) rather than `key=value` pairs so types are preserved.

Validate playbook changes with `ansible-playbook --syntax-check ansible/faz_log_search.yml` and by running against the test FAZ host — the playbook has no relation to the Flask app's `uv run pytest`/`ruff` checks.

## Architecture notes

### Flask app

- **Auth/CSRF/sessions**: bcrypt password hashes in `users.json`; `app/security.py` issues a CSRF token per session and validates it on every `POST`/`PUT`/`PATCH`/`DELETE` (`app/__init__.py`'s `before_request` hook, static-file requests excluded). Sessions carry a rolling lifetime (`PERMANENT_SESSION_LIFETIME`, 1 h) and an absolute cap (`SESSION_ABSOLUTE_LIFETIME`, default 10 h) enforced in `app/decorators.py`.
- **Access control**: tab visibility is per-group (`groups.json`'s `allowed_tabs`, checked by `@tab_required`); FAZ-target/ADOM visibility is a separate, orthogonal restriction — a group with `adom_restrict=True` limits its members to the `label`s listed in `allowed_adoms` (labels double as "ADOM" names for this purpose since each `faz_targets.json` entry is one ADOM/appliance). `groups.get_allowed_adoms()` returns `None` for "unrestricted" (admins, or any group without `adom_restrict`) and a concrete list otherwise; `dashboard_routes.api_dashboard()` filters `get_all_cached()`'s cards by this list before returning JSON.
- **FAZ health polling**: asynchronous and decoupled from request handling — `app/faz_health_cache.py` runs on its own APScheduler interval thread, never inside a Flask request. Dashboard API requests only ever read the last-known cached snapshot (`get_all_cached()`), so a slow or unreachable FAZ target never blocks a page load; a target with no cache entry yet (first poll still pending) reports `status: "gray"` rather than being omitted, and a target whose poll raised `FAZError`/network exception reports `status: "offline"` with the error message in `error`.
- **FAZ JSON-RPC auth**: `Authorization: Bearer <token>`, not `X-API-Key` — see the docstring at the top of `app/faz_client.py` for how this was determined (byte-identical `-11 No permission` errors from both `X-API-Key` and no header at all, while `Authorization: Bearer` succeeded, confirmed via direct curl comparison against `192.168.64.4`).
- **SNMP**: `pysnmp`'s asyncio v3 HLAPI (`app/faz_health_cache.py`'s `_snmp_get()`), SNMPv3 only (`UsmUserData` with configurable auth/priv protocol). FortiAnalyzer has no native memory-percentage OID, so mem% is computed from used-KB/total-KB, same pattern as FortiManager (ported from `4thealth`'s `infra_health_cache.py`). `SNMP_ENABLED=false` (the default) skips SNMP entirely and classifies every reachable target `green`.
- **Docker TLS**: TLS never terminates inside the `app` container — it always terminates at the `nginx` sidecar service (or, on RHEL bare-metal, at the host's own Nginx). This is why `COOKIE_SECURE` must be set explicitly rather than left on `auto` in both deployment paths.

### Legacy Ansible playbook (`ansible/faz_log_search.yml`)

- FortiAnalyzer's JSON-RPC log search is asynchronous: a submit call (`method: add`) returns a task ID (`tid`), and results are fetched by polling `method: get` against a URL that includes the `tid` until `result.percentage == 100`. The playbook implements this submit → poll → fetch loop with retries/delay controlled by `faz_search_timeout_seconds` and `faz_poll_delay_seconds`.
- The exact resource path and payload shape for log search (`faz_rpc_resource`, `faz_preflight_resource`) are **not yet finalized** — FAZ permissions and firmware version affect which route is exposed to a given API key. The playbook runs a `logview` preflight before the full search and fails with a diagnostic message (`No permission for the resource`) rather than silently proceeding, and `faz_fetch_uri_candidates` exists so alternate endpoint paths can be probed. This preflight pattern was later ported into `app/faz_client.py`'s own `preflight()` method. When adjusting these, check `api-info/*.json` first for the documented shape, and see the "Capture Exact GUI API Calls" section of [ansible/readme.md](ansible/readme.md) for how to reverse-engineer the exact request from the FAZ web UI's network traffic if the documented shape doesn't match observed behavior.
- Source/destination IP and port filters are translated into a FortiAnalyzer filter expression string (e.g. `srcip==10.1.1.0/24 and dstport==443`) inside the `Build the log filter expression` task in the playbook — `ANY`/`ALL` values are treated as "no filter" and omitted from the clause list. This logic is the intended source for Phase 3's `app/faz_client.py` filter-building.
- Time filters are normalized into a `faz_time_range` fact: explicit `faz_start_time`/`faz_end_time` take priority, then relative windows (`\d+m`, `\d+h`, `\d+d` are pattern-matched and converted to `last-n-minutes`/`last-n-hours`), else a default of `last-n-hours: 24`.
- Output is currently JSON-only, written to `ansible/output/faz_log_search.json` by default (`faz_output_dir`/`faz_output_file` are overridable). CSV export is planned but not yet implemented in the playbook — the Flask app's Phase 3 Log Search tab is expected to supersede this entirely.
