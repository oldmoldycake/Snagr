# Two-stage build (mirrors backend/Dockerfile): a build stage for wheels, then
# a slim runtime with only the venv. DINOv3 weights are NOT baked into the
# image — they are gated under Meta's license (D-V1). The container downloads
# them on first start into /home/vision/.cache/huggingface; compose mounts a
# named volume there so restarts don't re-download.

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

# Run as a non-root user
RUN useradd --create-home --uid 1000 vision && chown -R vision:vision /app
USER vision

EXPOSE 8100

CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8100"]
