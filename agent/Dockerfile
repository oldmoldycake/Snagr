# Two-stage build (mirrors backend/Dockerfile): a build stage with compilers
# for asyncpg wheels, then a slim runtime with only the venv. No browser deps —
# the agent drives the external Playwright MCP container (PLAYWRIGHT_MCP_URL).

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
COPY *.py ./

# Run as a non-root user; /app must stay writable — main.py logs to ./scraper.log
RUN useradd --create-home --uid 1000 snagr && chown -R snagr:snagr /app
USER snagr

# One full scrape pass, then exit (the nightly job). The compose `agent`
# service overrides this with a --consume / --ground-only ticker loop.
CMD ["python", "main.py"]
