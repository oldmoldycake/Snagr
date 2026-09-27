"""Settings that must stop the backend starting rather than run unsafely.

Whoever knows JWT_SECRET can sign an access token naming any user, admins
included, so a secret anyone could guess means sessions anyone could forge.
`_env_file=None` keeps the developer's own backend/.env out of these tests.
"""

import pytest
from app.config import Settings
from pydantic import ValidationError


@pytest.mark.parametrize(
    "secret",
    [
        "CHANGE_ME",  # backend/.env.example's placeholder
        "dev-only-change-me",
        "change-me-change-me-change-me-change-me",  # long enough, still a placeholder
        "a" * 31,
        "é" * 15 + "a",  # 31 bytes, 16 characters: the limit is bytes
    ],
)
def test_a_guessable_jwt_secret_is_refused(secret):
    with pytest.raises(ValidationError, match="JWT_SECRET"):
        Settings(_env_file=None, JWT_SECRET=secret)


def test_jwt_secret_has_no_default(monkeypatch):
    monkeypatch.delenv("JWT_SECRET")

    with pytest.raises(ValidationError, match="JWT_SECRET"):
        Settings(_env_file=None)


def test_a_32_byte_secret_is_accepted():
    assert Settings(_env_file=None, JWT_SECRET="a" * 32).JWT_SECRET == "a" * 32
