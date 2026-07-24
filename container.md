# Docker Deployment

This covers running 4tlog as a container via Docker Compose — the
alternative to the RHEL bare-metal path in `docs/deployment.md`.

## Prerequisites

- Docker Engine 20.10+
- Docker Compose v2 (the `docker compose` subcommand, not the standalone
  `docker-compose` binary)

## Quick sequence

```bash
cp .env.example .env
# Fill in SECRET_KEY — generate one with:
#   docker compose run --rm app uv run python manage_users.py secret
# and paste the result into .env.

cp users.example.json users.json
cp groups.example.json groups.json

# Create the first admin account (users.json/groups.json are bind-mounted,
# so this writes to the host files):
docker compose run --rm app uv run python manage_users.py add admin --role admin

docker compose up -d
```

## TLS

The container listens on plain HTTP on port 8100. TLS is expected to
terminate at a reverse proxy (Nginx, a load balancer, etc.) placed in front
of the container — the Dockerfile does not bake in or mount any certs for
TLS termination inside the container in Phase 1. Set `COOKIE_SECURE=true`
and `TRUSTED_PROXY_COUNT` accordingly in `.env` for that topology (see
`docs/deployment.md` §5 for the reasoning).

**Planned (Phase 2):** add a reverse-proxy service (Nginx or Caddy) to
`docker-compose.yml` that terminates TLS and proxies plain HTTP to
`app:8100` over the internal Docker network — the same shape as the
Nginx config in `docs/deployment.md` §3/§5, just pointing `proxy_pass` at
`app:8100` instead of `127.0.0.1:8100`.
