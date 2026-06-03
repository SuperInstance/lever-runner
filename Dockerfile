FROM python:3.11-slim AS runtime

# Security: run as non-root
RUN groupadd -r lever && useradd -r -g lever -d /home/lever -s /sbin/nologin lever

WORKDIR /app

# Install system deps needed by sentence-transformers / torch CPU
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
        build-essential \
        curl \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .
RUN pip install --no-cache-dir -e .

# Create sandbox and data dirs owned by lever
RUN mkdir -p /tmp/lever-runner /home/lever/data && \
    chown -R lever:lever /tmp/lever-runner /home/lever/data

ENV SANDBOX_ROOT=/tmp/lever-runner
ENV LANCEDB_PATH=/home/lever/data/lancedb
ENV HTTP_PORT=8765
ENV HTTP_BIND=0.0.0.0

USER lever
EXPOSE 8765

HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
    CMD curl -f http://localhost:8765/healthz || exit 1

CMD ["python", "-m", "lever_runner.http_api"]
