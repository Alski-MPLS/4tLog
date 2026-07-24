# 4tlog

A Flask web application for interacting with FortiAnalyzer. Phase 1 provides
a working dashboard frame with bcrypt login, group-based access control, an
admin interface for managing users, groups, and targets, plus placeholder tabs
for FortiAnalyzer health monitoring (Phase 2) and log search with filtering,
pagination, and export (Phase 3).

See [CLAUDE.md](CLAUDE.md) for architecture notes and
[docs/superpowers/specs/2026-07-24-web-app-design.md](docs/superpowers/specs/2026-07-24-web-app-design.md)
for the full design.

## Current features (Phase 1)

- **Authentication**: bcrypt-secured local user accounts
- **Admin Tab**: manage users and groups, configure FAZ targets, view system logs
- **Dashboard Tab**: placeholder for FortiAnalyzer health cards (Phase 2)
- **Log Search Tab**: placeholder for query builder and results (Phase 3)
- **Deployment**: Docker and RHEL bare-metal (Gunicorn/Nginx/systemd)

## Quick start (development)

```bash
uv sync
cp .env.example .env               # set SECRET_KEY (uv run python manage_users.py secret)
cp users.example.json users.json
cp groups.example.json groups.json
uv run python manage_users.py add admin --role admin
uv run python wsgi.py              # http://localhost:5000 (or https://localhost:5443 with certs/)
```

## Deployment

- Docker: see [container.md](container.md)
- RHEL bare-metal: see [docs/deployment.md](docs/deployment.md)

## Legacy Ansible scaffold

The original proof-of-concept for FAZ log search was an Ansible playbook.
It will be superseded by the web app's FAZ client (planned for Phase 2) but
remains in the repo for reference — see [ansible/readme.md](ansible/readme.md).
