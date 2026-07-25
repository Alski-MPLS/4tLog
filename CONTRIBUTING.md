# Contributing

Thanks for contributing to 4tlog.

## Development Setup

```bash
uv sync
cp .env.example .env
cp users.example.json users.json
cp groups.example.json groups.json
cp faz_targets.example.json faz_targets.json
uv run python manage_users.py secret
uv run python manage_users.py add admin --role admin
```

Set the generated secret in `.env`, then start the app:

```bash
uv run python wsgi.py
```

## Before Opening a Pull Request

Run the local checks:

```bash
uv run ruff check .
uv run pytest -q
```

## Scope Guidelines

- Keep changes focused on one problem or feature.
- Add or update tests for behavior changes.
- Preserve the example/runtime-data split: real `.env`, `users.json`, `groups.json`,
  `faz_targets.json`, and local certs stay out of version control.
- Do not commit API tokens, vault files with real secrets, or local deployment data.
- Update documentation when setup, behavior, or operator workflows change.

## Design Notes

- The Flask app is the primary interface.
- The Ansible playbook remains as a reference and CLI path.
- Background FAZ health polling is cache-based; request handlers should not block on
  live health checks.

See [docs/superpowers/README.md](docs/superpowers/README.md) for contributor-facing
architecture and roadmap notes.