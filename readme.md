# 4tlog

A web dashboard for monitoring FortiAnalyzer health and searching FortiAnalyzer
traffic/event logs by source/destination IP, port, and time window, with
CSV/JSON/PDF export.

See [CLAUDE.md](CLAUDE.md) for architecture notes and
[docs/superpowers/specs/2026-07-24-web-app-design.md](docs/superpowers/specs/2026-07-24-web-app-design.md)
for the full design.

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

- Docker: see [container.md](container.md) *(to be added alongside Docker packaging)*
- RHEL bare-metal: see [docs/deployment.md](docs/deployment.md)

## Legacy Ansible scaffold

The original proof-of-concept for FAZ log search was an Ansible playbook.
It has been superseded by the web app's `app/faz_client.py` (Phase 2) but
remains in the repo for reference — see [ansible/readme.md](ansible/readme.md).
