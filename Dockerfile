FROM python:3.12-slim

COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

WORKDIR /app

COPY pyproject.toml uv.lock ./

RUN uv sync --extra prod --no-dev

ENV PATH="/app/.venv/bin:$PATH"

COPY wsgi.py manage_users.py ./
COPY app/ app/

RUN useradd --system --no-create-home --shell /sbin/nologin appuser \
    && mkdir -p /app/certs \
    && chown -R appuser:appuser /app

ENV HOME=/tmp
USER appuser

EXPOSE 8100

CMD ["gunicorn", \
     "--workers", "2", \
     "--threads", "4", \
     "--worker-class", "gthread", \
     "--bind", "0.0.0.0:8100", \
     "--timeout", "120", \
     "--worker-tmp-dir", "/dev/shm", \
     "--access-logfile", "-", \
     "--error-logfile", "-", \
     "wsgi:app"]
