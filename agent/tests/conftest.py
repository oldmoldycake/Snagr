"""Environment defaults so pricing/database import without a real .env.

config.py and database.py read the environment at import time (database
asserts DATABASE_URL exists, pricing constructs a chat model), but these
tests never open a connection or call a model — the values only need to
exist, not work. setdefault runs before load_dotenv, so a local .env never
leaks real credentials or provider choices into the tests either.
"""

import os

os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://snagr:snagr@localhost:5432/snagr_test")
os.environ.setdefault("AI_PROVIDER", "openai")
os.environ.setdefault("AI_MODEL", "test-model")
os.environ.setdefault("AI_API_KEY", "test-key")
