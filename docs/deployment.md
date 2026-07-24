# RHEL Bare-Metal Deployment

This covers running 4tlog directly on a RHEL/Rocky/AlmaLinux host with
Gunicorn behind Nginx, managed by systemd — the alternative to the Docker
path in `container.md`.

## 1. System packages

```bash
sudo dnf install -y python3.12 python3.12-venv nginx git
curl -LsSf https://astral.sh/uv/install.sh | sh
```

## 2. Application user and directory

```bash
sudo useradd --system --home-dir /opt/4tlog --shell /sbin/nologin 4tlog
sudo mkdir -p /opt/4tlog
sudo chown 4tlog:4tlog /opt/4tlog
```

Clone the repo into `/opt/4tlog` as the `4tlog` user (or copy a release
tarball), then:

```bash
cd /opt/4tlog
sudo -u 4tlog uv sync --extra prod --no-dev
sudo -u 4tlog cp .env.example .env   # edit SECRET_KEY, etc.
sudo -u 4tlog cp users.example.json users.json
sudo -u 4tlog cp groups.example.json groups.json
sudo -u 4tlog uv run python manage_users.py secret     # paste into .env
sudo -u 4tlog uv run python manage_users.py add admin --role admin
```

## 3. TLS certificates

Terminate TLS at Nginx (recommended) rather than Gunicorn. Obtain a
certificate (e.g. via `certbot --nginx`) or place an internal CA-issued
cert/key at a path Nginx can read.

## 4. systemd unit

`/etc/systemd/system/4tlog.service`:

```ini
[Unit]
Description=4tlog Gunicorn service
After=network.target

[Service]
User=4tlog
Group=4tlog
WorkingDirectory=/opt/4tlog
Environment="PATH=/opt/4tlog/.venv/bin"
ExecStart=/opt/4tlog/.venv/bin/gunicorn \
    --workers 2 --threads 4 --worker-class gthread \
    --bind 127.0.0.1:8100 --timeout 120 \
    --access-logfile - --error-logfile - \
    wsgi:app
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now 4tlog
sudo systemctl status 4tlog
```

**Note on the `gthread` worker class:** later phases add a background health
polling thread. `sync` workers fork child processes and background threads
from the parent do not transfer — always use `--worker-class gthread`, even
though Phase 1 has no background threads yet.

## 5. Nginx reverse proxy

`/etc/nginx/conf.d/4tlog.conf`:

```nginx
server {
    listen 443 ssl;
    server_name 4tlog.example.internal;

    ssl_certificate     /etc/pki/tls/certs/4tlog.crt;
    ssl_certificate_key /etc/pki/tls/private/4tlog.key;

    location / {
        proxy_pass http://127.0.0.1:8100;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto https;
    }
}

server {
    listen 80;
    server_name 4tlog.example.internal;
    return 301 https://$host$request_uri;
}
```

Set `TRUSTED_PROXY_COUNT=1` in `.env` so Flask trusts Nginx's
`X-Forwarded-*` headers for HSTS and client-IP-based rate limiting.

```bash
sudo systemctl enable --now nginx
sudo nginx -t && sudo systemctl reload nginx
```

## 6. Firewalld

```bash
sudo firewall-cmd --permanent --add-service=https
sudo firewall-cmd --permanent --add-service=http
sudo firewall-cmd --reload
```

## 7. SELinux

If SELinux is enforcing and Nginx refuses to proxy to Gunicorn:

```bash
sudo setsebool -P httpd_can_network_connect 1
```

## 8. Verify

```bash
curl -sf https://4tlog.example.internal/login | grep -q Password && echo OK
```
