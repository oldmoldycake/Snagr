"""Application settings, loaded from environment / .env via pydantic-settings.

Every module reads config from the single `settings` instance here — never
`os.getenv` directly. Keeps the env surface in one auditable place.
"""

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # Async driver required: postgresql+asyncpg://... (NOT plain postgresql://)
    DATABASE_URL: str = "postgresql+asyncpg://snagr:CHANGE_ME@localhost:5432/snagr"

    # Auth
    JWT_SECRET: str = (
        "dev-only-change-me"  # `python -c 'import secrets; print(secrets.token_urlsafe(48))'`
    )
    ACCESS_TTL_MIN: int = 15  # short-lived access JWT
    REFRESH_TTL_DAYS: int = 30  # DB-backed rotating refresh token
    cookie_secure: bool = False  # True in prod (HTTPS only)

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

    # Instance / notifications
    APP_VERSION: str = "0.1.0"
    NTFY_SERVER_URL: str | None = None  # drives InstanceInfo.ntfy_server_url


settings = Settings()
