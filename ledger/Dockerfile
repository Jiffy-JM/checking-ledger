FROM python:3.12-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    DATA_DIR=/data

WORKDIR /app
COPY requirements.txt .
RUN pip install -r requirements.txt \
 && useradd --uid 10001 --no-create-home --shell /usr/sbin/nologin ledger \
 && mkdir -p /data && chown ledger:ledger /data

COPY app.py ledger_core.py networth.py themes.py backup_status.py ./
COPY templates ./templates
COPY static ./static

# Runs as an unprivileged user, never root.
USER ledger
EXPOSE 3000
HEALTHCHECK --interval=30s --timeout=3s --start-period=10s \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:3000/healthz', timeout=2)"

# 0.0.0.0 here means "all of the container's own network interfaces",
# which only Docker can reach. What your network can reach is decided by
# the ports line in docker-compose.yml (HOST_IP in .env).
# One worker on purpose: all writes to the CSV files go through one process.
# The access log records the path only, never the part after "?", so amounts
# typed into a what-if don't end up in the logs.
CMD ["gunicorn", "--workers", "1", "--threads", "4", "--bind", "0.0.0.0:3000", "--access-logfile", "-",
     "--access-logformat", "%(t)s %(m)s %(U)s %(s)s", "app:create_app()"]
