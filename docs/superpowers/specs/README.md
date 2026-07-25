# Architecture Summary

## Application Shape

4tlog is a Flask application with:

- app-factory startup in `app/__init__.py`
- route modules under `app/routes/`
- local JSON-backed runtime stores for users, groups, and FAZ targets
- a background health cache for Dashboard data
- a JSON-RPC client for FortiAnalyzer health and log-search calls

## Operational Rules

- Real runtime data lives in `.env`, `users.json`, `groups.json`, `faz_targets.json`, and
  local TLS cert files; example templates are the committed source of truth.
- The Dashboard should serve cached state rather than blocking on live appliance checks.
- Log Search behavior should remain covered by focused tests for filter parsing and route
  validation.

## Deployment Modes

- Local development via `uv run python wsgi.py`
- Docker with Nginx TLS termination
- RHEL-family deployment with Gunicorn and Nginx

## Reference Material

- `api-info/` contains FortiAnalyzer API reference documents used during development.
- The test appliance at `192.168.64.4` is intentionally referenced in examples and docs.