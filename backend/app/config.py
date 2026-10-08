"""Application settings, loaded from environment / .env via pydantic-settings.

Every module reads config from the single `settings` instance here — never
`os.getenv` directly. Keeps the env surface in one auditable place.
"""

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Every env var the backend reads; unset ones fall back to the dev defaults below
    (JWT_SECRET has none — it must be set)."""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # Async driver required: postgresql+asyncpg://... (NOT plain postgresql://)
    DATABASE_URL: str = "postgresql+asyncpg://snagr:CHANGE_ME@localhost:5432/snagr"

    # Auth. No default: anyone who knows the secret can sign an access token for
    # any user, so a published value (a default, .env.example's placeholder) is
    # as good as none. Generate one:
    #   python -c 'import secrets; print(secrets.token_urlsafe(48))'
    JWT_SECRET: str
    ACCESS_TTL_MIN: int = 15  # short-lived access JWT
    REFRESH_TTL_DAYS: int = 30  # DB-backed rotating refresh token
    cookie_secure: bool = False  # True in prod (HTTPS only)

    @field_validator("JWT_SECRET")
    @classmethod
    def _refuse_weak_jwt_secret(cls, value: str) -> str:
        """Refuse to start on a placeholder or a guessable secret, rather than
        run with sessions anyone can forge."""
        if "changeme" in value.lower().replace("_", "").replace("-", ""):
            raise ValueError("JWT_SECRET is still the placeholder; generate a real one")
        if len(value.encode()) < 32:
            raise ValueError("JWT_SECRET must be at least 32 bytes")
        return value

    # Registration: the very first user can ALWAYS register (bootstrap admin).
    # After that, this toggle decides: True = open self-signup, False = invite-only.
    REGISTRATION_OPEN: bool = False

    # SSO via OIDC (e.g. Authentik) — enabled iff the first three are all set.
    OIDC_ISSUER: str | None = None  # e.g. https://auth.lan/application/o/snagr/
    OIDC_CLIENT_ID: str | None = None
    OIDC_CLIENT_SECRET: str | None = None
    OIDC_PROVIDER_NAME: str = "SSO"  # login-button label, e.g. "Authentik"
    OIDC_REDIRECT_URI: str | None = None  # override when the request-derived URL is wrong (proxies)

    @property
    def oidc_enabled(self) -> bool:
        """SSO is on only when the three OIDC_* essentials are all set."""
        return bool(self.OIDC_ISSUER and self.OIDC_CLIENT_ID and self.OIDC_CLIENT_SECRET)

    # Visual authenticity: the vision sidecar's URL. Unset = the feature is off —
    # vision list routes return empty data, vision mutations 503, UI hides it all.
    VISION_SIDECAR_URL: str | None = None

    @property
    def vision_enabled(self) -> bool:
        """Vision is on only when the sidecar URL is configured."""
        return bool(self.VISION_SIDECAR_URL)

    # Agent access — the MCP endpoint (POST /api/mcp) and API tokens (bearer auth
    # on the REST API). False removes both and hides the Settings tab.
    MCP_ENABLED: bool = True

    # How often the hunter re-reads a tracked listing's price. The agent owns
    # the cadence; the backend reports the default (InstanceInfo, the facts
    # line) and refuses a per-watch interval below the floor. Set the SAME
    # values in agent/.env — the two components do not share a file (the
    # VISION_SIDECAR_URL precedent).
    RECHECK_INTERVAL_MINUTES: int = 30
    RECHECK_INTERVAL_FLOOR_MINUTES: int = 5

    # The hunter's kill switch. The agent is what stops hunting; the backend
    # needs it to refuse "hunt now" (409 hunting_disabled) instead of queueing
    # work nothing will claim, and to tell the UI (InstanceInfo.hunt_enabled).
    # Set the SAME value in agent/.env.
    HUNT_ENABLED: bool = True

    # Instance / notifications
    APP_VERSION: str = "0.9.1"  # x-release-please-version
    NTFY_SERVER_URL: str | None = None  # drives InstanceInfo.ntfy_server_url


settings = Settings()
