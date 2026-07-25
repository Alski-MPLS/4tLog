# 4tlog

A Flask web application for interacting with FortiAnalyzer. Phase 1 provides
a working dashboard frame with bcrypt login, group-based access control, and
an admin interface for managing users, groups, and targets. Phase 2 makes the
Dashboard tab real — live FortiAnalyzer health cards backed by a background
poller, plus an Admin sub-tab for managing which FAZ appliances are polled —
and adds TLS for the Docker deployment (reverse-proxy container terminating
TLS in front of the app, mirroring the RHEL/Nginx setup) — see
[container.md](container.md). The Log Search tab (filtering, pagination,
export) remains a placeholder pending Phase 3.

See [CLAUDE.md](CLAUDE.md) for architecture notes and
[docs/superpowers/specs/2026-07-24-web-app-design.md](docs/superpowers/specs/2026-07-24-web-app-design.md)
for the full design.

## Current features

- **Authentication**: bcrypt-secured local user accounts
- **Admin Tab**: view users (read-only — accounts are managed via the
  `manage_users.py` CLI) and manage groups/tab permissions, view system logs
- **Admin → FAZ Targets**: CRUD for the FortiAnalyzer appliances the
  Dashboard polls (label, host, ADOM, bearer token, optional per-target SNMP
  credential overrides) — backed by `faz_targets.json`, edits take effect on
  the next poll cycle without an app restart
- **Dashboard Tab**: live FortiAnalyzer health cards — status/hostname/
  version/serial/HA mode/HA role/disk usage from FAZ's JSON-RPC status API,
  plus CPU/mem gauges from SNMPv3 when `SNMP_ENABLED=true` — refreshed by a
  background poller so page loads never block on a live FAZ/SNMP call.
  Group membership can restrict which targets a user's cards show, reusing
  the same `adom_restrict`/`allowed_adoms` group fields as ADOM access
  control.
- **Log Search Tab**: placeholder for query builder and results (Phase 3)
- **Deployment**: Docker (with TLS via an Nginx reverse-proxy sidecar
  container) and RHEL bare-metal (Gunicorn/Nginx/systemd)

## Quick start (development)

```bash
uv sync
cp .env.example .env               # set SECRET_KEY (uv run python manage_users.py secret)
cp users.example.json users.json
cp groups.example.json groups.json
cp faz_targets.example.json faz_targets.json
uv run python manage_users.py add admin --role admin
uv run python wsgi.py              # http://localhost:5443 (PORT defaults to 5443; add certs/ for HTTPS)
```

## Deployment

- Docker: see [container.md](container.md)
- RHEL bare-metal: see [docs/deployment.md](docs/deployment.md)

## Legacy Ansible scaffold

The original proof-of-concept for FAZ log search was an Ansible playbook.
`app/faz_client.py` (Phase 2) already replaces its health/status calls;
the playbook's log-search filter-building logic will be ported into
`faz_client.py`'s `search_logs()`/`build_filter_expression()` in Phase 3.
Until then the playbook remains in the repo for reference — see
[ansible/readme.md](ansible/readme.md).
