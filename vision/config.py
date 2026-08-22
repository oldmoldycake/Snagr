"""Environment-driven configuration for the vision sidecar, loaded from .env.

This service is LAN-internal and unauthenticated in v1 (D-V1) — the same
trust posture as the Playwright MCP sidecar. Never expose it, or the minio it
fronts, to the public internet.
"""

import os

from dotenv import load_dotenv

load_dotenv()

# Sync driver required: postgresql+psycopg://... — the sidecar's handlers are
# threadpool-sync (embedding is CPU-bound), unlike the async backend.
DATABASE_URL = os.getenv("DATABASE_URL")

# Object store (any S3-compatible endpoint; the compose default is the bundled
# minio). The sidecar is the ONLY S3 client in the project (D-V3), so these
# credentials live here and nowhere else.
S3_ENDPOINT = os.getenv("S3_ENDPOINT", "http://localhost:9000")
S3_BUCKET = os.getenv("S3_BUCKET", "snagr-vision")
S3_ACCESS_KEY = os.getenv("S3_ACCESS_KEY")
S3_SECRET_KEY = os.getenv("S3_SECRET_KEY")

# DINOv3 weights are gated on Hugging Face under Meta's license and cannot be
# bundled (D-V1): the operator accepts the license, sets HF_TOKEN, and the
# first start downloads them. Without weights the service runs degraded — see
# embedder.LICENSE_HELP for the message every scoring call then returns.
HF_TOKEN = os.getenv("HF_TOKEN")
VISION_MODEL = os.getenv("VISION_MODEL", "facebook/dinov3-vits16plus-pretrain-lvd1689m")
# Must match the vector(384) columns from migration 009; the startup guard in
# app.py refuses to run a model that embeds at any other width.
EMBEDDING_DIM = 384

# Unreviewed listing images older than this are pruned by the daily GC (D-V12).
VISION_RETENTION_DAYS = int(os.getenv("VISION_RETENTION_DAYS", "90"))

PORT = int(os.getenv("PORT", "8100"))
