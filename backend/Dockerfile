# Two-stage build (mirrors frontend/Dockerfile): a build stage with compilers
# for asyncpg / argon2-cffi wheels, then a slim runtime with only the venv.

# --- Stage 1: build a self-contained virtualenv ---------------------------------
FROM python:3.14-slim AS build

ENV PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1

# build-essential covers any package without a prebuilt wheel for 3.14
RUN apt-get update \
    && apt-get install -y --no-install-recommends build-essential \
    && rm -rf /var/lib/apt/lists/*

RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# --- Stage 2: slim runtime (no compilers) ---------------------------------------
FROM python:3.14-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PATH="/opt/venv/bin:$PATH"

WORKDIR /app

COPY --from=build /opt/venv /opt/venv
COPY app ./app

# Uncomment once Alembic is initialized (getting-started step 2) so migrations
# ship in the image and can run on deploy:
# COPY migrations ./migrations
# COPY alembic.ini .

# Run as a non-root user
RUN useradd --create-home --uid 1000 snagr && chown -R snagr:snagr /app
USER snagr

EXPOSE 8000

# Single worker; scale with replicas. SSE (/api/events) needs long-lived
# connections — uvicorn handles those fine. nginx proxies /api to :8000.
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
