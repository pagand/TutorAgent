# ---- Build stage ----
FROM python:3.11-slim AS builder

WORKDIR /app

# gcc for psycopg2 and other C extensions; libpq-dev for postgres client
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    libpq-dev \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir --upgrade pip \
 && pip install --no-cache-dir -r requirements.txt

# ---- Runtime stage ----
FROM python:3.11-slim AS runtime

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    libpq-dev \
    && rm -rf /var/lib/apt/lists/*

# Copy installed packages from builder
COPY --from=builder /usr/local/lib/python3.11/site-packages /usr/local/lib/python3.11/site-packages
COPY --from=builder /usr/local/bin /usr/local/bin

# Non-root user (UID 1000 matches default ec2-user/ubuntu on most Linux AMIs)
RUN adduser --disabled-password --gecos "" --uid 1000 appuser

# Copy application code and set ownership
COPY . .
RUN mkdir -p /app/chroma_db /app/data /app/evaluation/data \
 && chown -R appuser:appuser /app

COPY entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

USER appuser

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=10s --start-period=120s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/')" || exit 1

ENTRYPOINT ["/entrypoint.sh"]
