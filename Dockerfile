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

# --workers 1: the FAZ health poller (app/faz_health_cache.py) keeps its
# scheduler and its polled-status cache in this process's memory only. With
# more than one Gunicorn worker, each pre-forked process would run its own
# independent scheduler/cache, doubling (or more) the actual FAZ/SNMP poll
# rate and causing dashboard status to flip-flop depending on which worker
# served a given request. Concurrency comes from threads instead.
CMD ["gunicorn", \
     "--workers", "1", \
     "--threads", "8", \
     "--worker-class", "gthread", \
     "--bind", "0.0.0.0:8100", \
     "--timeout", "120", \
     "--worker-tmp-dir", "/dev/shm", \
     "--access-logfile", "-", \
     "--error-logfile", "-", \
     "wsgi:app"]
