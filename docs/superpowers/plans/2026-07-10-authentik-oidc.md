# Authentik / OIDC Login Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Sign in to Snagr through Authentik (any OIDC provider) alongside password login, marrying existing local accounts by verified email and auto-creating unknown users.

**Architecture:** Two new GET routes in `routers/auth.py` do the browser redirects; a new `services/oidc.py` owns the whole IdP conversation (discovery, PKCE, code exchange, ID-token validation, user linking). Once a user is resolved, the existing `_start_session()` issues the normal cookie pair — the session layer is untouched. The frontend learns about SSO via one new `InstanceInfo` field.

**Tech Stack:** FastAPI, async SQLAlchemy 2.0, Alembic, `authlib` (new dep — token exchange + JWKS/ID-token validation), React 19 + TanStack Query.

**Spec:** `docs/superpowers/specs/2026-07-10-authentik-oidc-design.md` — read it first.

## Global Constraints

- Run every backend tool via `backend/venv`: `./venv/bin/pytest`, `./venv/bin/alembic` (from `backend/`). Frontend commands run from `frontend/`.
- Tests need a reachable Postgres; conftest redirects to a throwaway `snagr_test` DB automatically.
- Errors always via `raise err(status, code, message, **extra)` — never FastAPI's `{"detail": ...}`. Exception: the two OIDC routes redirect on failure (`/login?error=sso_failed`), never JSON, because the browser is mid-navigation.
- Mutating requests in tests carry `headers=CSRF` (from `tests.conftest`). The two OIDC routes are GET — `csrf_guard` does not apply; the OIDC `state` parameter is the flow's CSRF protection.
- `/api/auth/*` must never return 401 in a way that trips the client refresh loop — the OIDC routes only ever 302 (or 404 for `/oidc/login` when SSO is off).
- Schema changes go through Alembic (`alembic revision --autogenerate`, inspect, then `alembic check` must pass). Never `create_all` against the live DB.
- Env vars are read ONLY in `app/config.py` via the `settings` singleton.
- Frontend contract mirrors: any `types.ts` change is mirrored field-for-field in `app/schemas/` and in `mocks/handlers.ts`.
- Commit after every task (bodies below); end commit messages with the project's usual style (imperative, no attribution footer needed beyond your harness rules).

---

### Task 1: Config settings, `users.oidc_sub` column, migration

**Files:**
- Modify: `backend/app/config.py`
- Modify: `backend/app/models.py:35` (User model)
- Create: `backend/migrations/versions/003_users_oidc_sub.py` (via autogenerate, then normalize)
- Modify: `backend/.env.example`
- Create: `backend/tests/test_oidc.py`

**Interfaces:**
- Produces: `settings.OIDC_ISSUER | OIDC_CLIENT_ID | OIDC_CLIENT_SECRET: str | None`, `settings.OIDC_PROVIDER_NAME: str = "SSO"`, `settings.OIDC_REDIRECT_URI: str | None`, property `settings.oidc_enabled: bool`; ORM column `User.oidc_sub: str | None` (unique). Every later task depends on these exact names.

- [ ] **Step 1: Write the failing test**

Create `backend/tests/test_oidc.py`:

```python
"""OIDC/SSO login — config, service logic, and the two auth routes.

The IdP itself never exists in these tests: protocol helpers are
monkeypatched at the service boundary, so everything from the routes down to
the DB is covered without a network.
"""

import pytest

from app.config import settings


@pytest.fixture(autouse=True)
def _oidc_settings(monkeypatch):
    """Every test in this file runs with SSO configured (individual tests
    un-set pieces to probe the disabled state)."""
    monkeypatch.setattr(settings, "OIDC_ISSUER", "https://idp.test/application/o/snagr/")
    monkeypatch.setattr(settings, "OIDC_CLIENT_ID", "snagr-client")
    monkeypatch.setattr(settings, "OIDC_CLIENT_SECRET", "s3cret")
    monkeypatch.setattr(settings, "OIDC_PROVIDER_NAME", "Authentik")


# --- config -------------------------------------------------------------------

def test_oidc_enabled_requires_all_three(monkeypatch):
    assert settings.oidc_enabled is True          # fixture set all three
    monkeypatch.setattr(settings, "OIDC_CLIENT_SECRET", None)
    assert settings.oidc_enabled is False
```

- [ ] **Step 2: Run test to verify it fails**

Run (from `backend/`): `./venv/bin/pytest tests/test_oidc.py -v`
Expected: ERROR/FAIL — `AttributeError: ... has no attribute 'OIDC_ISSUER'` (monkeypatch refuses to set attributes that don't exist).

- [ ] **Step 3: Add the settings**

In `backend/app/config.py`, after the `REGISTRATION_OPEN` block, add:

```python
    # SSO via OIDC (e.g. Authentik) — enabled iff the first three are all set.
    OIDC_ISSUER: str | None = None          # e.g. https://auth.lan/application/o/snagr/
    OIDC_CLIENT_ID: str | None = None
    OIDC_CLIENT_SECRET: str | None = None
    OIDC_PROVIDER_NAME: str = "SSO"         # login-button label, e.g. "Authentik"
    OIDC_REDIRECT_URI: str | None = None    # override when the request-derived URL is wrong (proxies)

    @property
    def oidc_enabled(self) -> bool:
        """SSO is on only when the three OIDC_* essentials are all set."""
        return bool(self.OIDC_ISSUER and self.OIDC_CLIENT_ID and self.OIDC_CLIENT_SECRET)
```

(Keep the `@property` inside the `Settings` class, above the `settings = Settings()` line.)

- [ ] **Step 4: Run test to verify it passes**

Run: `./venv/bin/pytest tests/test_oidc.py -v`
Expected: PASS (1 test).

- [ ] **Step 5: Add the ORM column**

In `backend/app/models.py`, in `class User`, directly under the `password_hash` line, add:

```python
    oidc_sub:       Mapped[str | None]    = mapped_column(Text, unique=True)        # + api (OIDC subject; NULL = password-only)
```

- [ ] **Step 6: Generate + normalize the migration**

Run (from `backend/`, needs the dev DB up and at head):

```bash
./venv/bin/alembic upgrade head
./venv/bin/alembic revision --autogenerate -m "users oidc_sub"
```

Inspect the generated file in `migrations/versions/`: it must contain ONLY an `add_column("users", sa.Column("oidc_sub", sa.Text(), nullable=True))` plus a unique constraint/index on it — nothing else. (If anything else appears, models and migrations had drifted; stop and report.) Then normalize to match repo convention: rename the file to `003_users_oidc_sub.py`, set `revision: str = '003'` and `down_revision ... = '002'`, and replace the module docstring's first lines with:

```
users.oidc_sub for OIDC/SSO login

Links a local account to its IdP identity (Authentik). NULL = password-only
user. Unique — one local account per IdP subject.
```

Keep the autogenerated constraint name exactly as emitted (that's what keeps `alembic check` green).

- [ ] **Step 7: Apply + verify migrations agree with models**

```bash
./venv/bin/alembic upgrade head
./venv/bin/alembic check
```

Expected: `No new upgrade operations detected.`

- [ ] **Step 8: Document the env vars**

Append to `backend/.env.example`:

```bash
# SSO via OIDC (e.g. Authentik) — all three required to enable; leave unset to disable.
# Register the redirect URL  https://<public-host>/api/auth/oidc/callback  at the IdP.
#OIDC_ISSUER=https://auth.example.com/application/o/snagr/
#OIDC_CLIENT_ID=
#OIDC_CLIENT_SECRET=
#OIDC_PROVIDER_NAME=Authentik
# Only needed when a proxy hides the public host from the backend:
#OIDC_REDIRECT_URI=
```

- [ ] **Step 9: Full suite still green**

Run: `./venv/bin/pytest`
Expected: all tests pass (schema change is additive).

- [ ] **Step 10: Commit**

```bash
git add backend/app/config.py backend/app/models.py backend/migrations/versions/003_users_oidc_sub.py backend/.env.example backend/tests/test_oidc.py
git commit -m "feat(oidc): OIDC settings + users.oidc_sub column"
```

---

### Task 2: `InstanceInfo.oidc_provider_name` (backend + frontend contract)

**Files:**
- Modify: `backend/app/schemas/auth.py:16-19` (InstanceInfo)
- Modify: `backend/app/routers/instance.py`
- Modify: `frontend/src/api/types.ts:41-47` (InstanceInfo)
- Modify: `frontend/src/mocks/handlers.ts:153-160` (instance handler)
- Test: `backend/tests/test_oidc.py`

**Interfaces:**
- Consumes: `settings.oidc_enabled`, `settings.OIDC_PROVIDER_NAME` (Task 1).
- Produces: `InstanceInfo.oidc_provider_name: str | null` — `null` = SSO disabled. Task 7's login page reads exactly this field.

- [ ] **Step 1: Write the failing test**

Append to `backend/tests/test_oidc.py`:

```python
# --- instance contract ----------------------------------------------------------

async def test_instance_reports_oidc(client, monkeypatch):
    res = await client.get("/api/instance")
    assert res.json()["oidc_provider_name"] == "Authentik"
    monkeypatch.setattr(settings, "OIDC_ISSUER", None)   # disable -> null
    res = await client.get("/api/instance")
    assert res.json()["oidc_provider_name"] is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `./venv/bin/pytest tests/test_oidc.py -v`
Expected: FAIL — `KeyError: 'oidc_provider_name'`.

- [ ] **Step 3: Implement**

In `backend/app/schemas/auth.py`, extend `InstanceInfo`:

```python
class InstanceInfo(BaseModel):
    version: str
    ntfy_server_url: str | None
    registration_open: bool
    oidc_provider_name: str | None    # null = SSO not configured
```

In `backend/app/routers/instance.py`, add the field to the return:

```python
    return InstanceInfo(
        version=settings.APP_VERSION,
        ntfy_server_url=settings.NTFY_SERVER_URL or None,
        registration_open=settings.REGISTRATION_OPEN or (user_count or 0) == 0,
        oidc_provider_name=settings.OIDC_PROVIDER_NAME if settings.oidc_enabled else None,
    )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `./venv/bin/pytest tests/test_oidc.py -v`
Expected: PASS.

- [ ] **Step 5: Mirror in the frontend contract**

In `frontend/src/api/types.ts`, extend `InstanceInfo`:

```ts
export interface InstanceInfo {
  version: string
  /** null when the admin hasn't configured NTFY_SERVER_URL */
  ntfy_server_url: string | null
  /** true only while the instance has zero users (first-admin bootstrap) */
  registration_open: boolean
  /** SSO login-button label (e.g. "Authentik"); null when OIDC is not configured */
  oidc_provider_name: string | null
}
```

In `frontend/src/mocks/handlers.ts`, in the `/api/instance` handler, add one line after `registration_open`:

```ts
      oidc_provider_name: null,
```

(Mock mode hides the SSO button — MSW cannot simulate a cross-site redirect flow.)

- [ ] **Step 6: Frontend typechecks**

Run (from `frontend/`): `npm run build`
Expected: succeeds (fails on type errors, so this IS the typecheck).

- [ ] **Step 7: Commit**

```bash
git add backend/app/schemas/auth.py backend/app/routers/instance.py backend/tests/test_oidc.py frontend/src/api/types.ts frontend/src/mocks/handlers.ts
git commit -m "feat(oidc): expose oidc_provider_name in InstanceInfo"
```

---

### Task 3: `services/oidc.py` — `resolve_oidc_user` (the linking logic)

**Files:**
- Create: `backend/app/services/oidc.py`
- Modify: `backend/STRUCTURE.md` (tree + "four services" count)
- Modify: `CLAUDE.md` ("four services" count)
- Test: `backend/tests/test_oidc.py`

**Interfaces:**
- Consumes: `User.oidc_sub` (Task 1).
- Produces: `class OidcError(Exception)` and `async def resolve_oidc_user(db: AsyncSession, claims: dict) -> User`. Task 5's callback calls both. Claims dict uses standard OIDC keys: `sub`, `email`, `email_verified`.

- [ ] **Step 1: Write the failing tests**

Append to `backend/tests/test_oidc.py` — also add these imports at the top of the file (below the existing ones):

```python
from app.core.security import hash_password
from app.models import User
from app.services import oidc
```

```python
# --- resolve_oidc_user: sub-first, marry-by-verified-email, auto-create ---------

CLAIMS = {"sub": "authentik-sub-1", "email": "sso@example.com", "email_verified": True}


async def _seed_user(db_session, email, **kw):
    async with db_session() as s:
        u = User(email=email, email_verified=True, **kw)
        s.add(u)
        await s.commit()
        return u.id


async def test_resolve_matches_by_sub(db_session):
    uid = await _seed_user(db_session, "someone@else.com", oidc_sub="authentik-sub-1")
    async with db_session() as s:
        user = await oidc.resolve_oidc_user(s, CLAIMS)
    assert user.id == uid            # sub wins even though the email differs


async def test_resolve_marries_verified_email(db_session):
    uid = await _seed_user(db_session, "sso@example.com",
                           password_hash=hash_password("pw12345678"))
    async with db_session() as s:
        user = await oidc.resolve_oidc_user(s, CLAIMS)
        await s.commit()
    assert user.id == uid
    async with db_session() as s:
        assert (await s.get(User, uid)).oidc_sub == "authentik-sub-1"   # married


async def test_resolve_refuses_unverified_email(db_session):
    uid = await _seed_user(db_session, "sso@example.com")
    async with db_session() as s:
        with pytest.raises(oidc.OidcError):
            await oidc.resolve_oidc_user(s, {**CLAIMS, "email_verified": False})
    async with db_session() as s:
        assert (await s.get(User, uid)).oidc_sub is None                # NOT married


async def test_resolve_autocreates_unknown_user(db_session):
    async with db_session() as s:
        user = await oidc.resolve_oidc_user(s, CLAIMS)
        await s.commit()
    assert user.role == "user"
    assert user.oidc_sub == "authentik-sub-1"
    assert user.password_hash is None


async def test_resolve_rejects_inactive_user(db_session):
    await _seed_user(db_session, "sso@example.com",
                     oidc_sub="authentik-sub-1", is_active=False)
    async with db_session() as s:
        with pytest.raises(oidc.OidcError):
            await oidc.resolve_oidc_user(s, CLAIMS)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `./venv/bin/pytest tests/test_oidc.py -v`
Expected: the new tests ERROR with `ImportError`/`ModuleNotFoundError` for `app.services.oidc`.

- [ ] **Step 3: Create the service module**

Create `backend/app/services/oidc.py`:

```python
"""OIDC login (Authentik or any OIDC provider) — the whole IdP conversation.

Spec: docs/superpowers/specs/2026-07-10-authentik-oidc-design.md

  /api/auth/oidc/login    -> new_flow() + build_authorize_url() -> 302 to IdP
  /api/auth/oidc/callback -> unpack_flow() -> exchange_code()
                             -> validate_id_token() -> resolve_oidc_user()

Every failure raises OidcError; the router maps them all to one redirect
(/login?error=sso_failed) and logs the detail server-side.
"""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import User


class OidcError(Exception):
    """Any OIDC failure; the callback maps every one to the same redirect."""


# --- account linking ----------------------------------------------------------

async def resolve_oidc_user(db: AsyncSession, claims: dict) -> User:
    """ID-token claims -> local User. Sub-first, marry-by-verified-email
    second, auto-create third (spec decision: Authentik is the access gate).
    Raises OidcError for inactive users or unusable claims. Caller commits."""
    sub = claims.get("sub")
    if not sub:
        raise OidcError("ID token has no sub")
    email = claims.get("email")
    email_ok = claims.get("email_verified") is True and bool(email)

    # 1. the stable link — survives email changes at the IdP
    user = await db.scalar(select(User).where(User.oidc_sub == sub))

    # 2. the marriage: claim an existing local account, once. Only a VERIFIED
    #    email may do this — an unverified one could hijack someone's account.
    if user is None and email_ok:
        user = await db.scalar(select(User).where(User.email == email))
        if user is not None:
            user.oidc_sub = sub

    # 3. unknown at the IdP-approved door -> provision a fresh account
    if user is None:
        if not email_ok:
            raise OidcError("IdP did not supply a verified email")
        user = User(email=email, email_verified=True, role="user",
                    is_active=True, oidc_sub=sub)
        db.add(user)
        await db.flush()          # assign user.id for _start_session

    if not user.is_active:
        raise OidcError(f"account {user.id} is disabled")
    return user
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `./venv/bin/pytest tests/test_oidc.py -v`
Expected: PASS (7 tests).

- [ ] **Step 5: Update the docs that count services**

`backend/STRUCTURE.md` — in the tree under `services/`, after the `runs.py` line, add:

```
│       ├── oidc.py         # SSO: OIDC discovery, code exchange, ID-token validation, account linking
```

Same file, change `that's why only four services exist, not one per router.` to `that's why only five services exist, not one per router.`

`CLAUDE.md` — change `only four services exist, for real logic (item mapping, aggregation math, run lifecycle, SSE).` to `only five services exist, for real logic (item mapping, aggregation math, run lifecycle, SSE, OIDC login).`

- [ ] **Step 6: Commit**

```bash
git add backend/app/services/oidc.py backend/tests/test_oidc.py backend/STRUCTURE.md CLAUDE.md
git commit -m "feat(oidc): resolve_oidc_user account-linking service"
```

---

### Task 4: OIDC protocol helpers + `GET /api/auth/oidc/login`

**Files:**
- Modify: `backend/requirements.txt` (add `authlib`)
- Modify: `backend/app/services/oidc.py`
- Modify: `backend/app/routers/auth.py`
- Test: `backend/tests/test_oidc.py`

**Interfaces:**
- Consumes: `settings.oidc_enabled`, `OIDC_*` settings (Task 1), `OidcError` (Task 3).
- Produces (all in `app.services.oidc`): `new_flow() -> dict` (keys `state`, `nonce`, `verifier`), `pack_flow(flow: dict) -> str` / `unpack_flow(raw: str) -> dict`, `async build_authorize_url(redirect_uri: str, flow: dict) -> str`, module-level caches `_metadata: dict | None` and `_keyset` (tests stub `_metadata` directly). In `routers/auth.py`: `FLOW_COOKIE = "snagr_oidc_flow"`, `FLOW_PATH = "/api/auth/oidc"`, route `GET /api/auth/oidc/login`. Task 5 reuses all of these.

- [ ] **Step 1: Install the dependency**

Run (from `backend/`): `./venv/bin/pip install authlib`
Then add to `backend/requirements.txt` under the `# Auth` section:

```
authlib
```

- [ ] **Step 2: Write the failing tests**

Append to `backend/tests/test_oidc.py`:

```python
# --- GET /api/auth/oidc/login ---------------------------------------------------

FAKE_METADATA = {
    "issuer": "https://idp.test/application/o/snagr/",
    "authorization_endpoint": "https://idp.test/authorize",
    "token_endpoint": "https://idp.test/token",
    "jwks_uri": "https://idp.test/jwks",
}


async def test_oidc_login_redirects_to_idp(client, monkeypatch):
    monkeypatch.setattr(oidc, "_metadata", FAKE_METADATA)   # skip discovery HTTP
    res = await client.get("/api/auth/oidc/login")
    assert res.status_code == 302
    loc = res.headers["location"]
    assert loc.startswith("https://idp.test/authorize?")
    assert "client_id=snagr-client" in loc
    assert "code_challenge_method=S256" in loc
    assert "state=" in loc and "nonce=" in loc
    assert "snagr_oidc_flow" in res.cookies                 # flow cookie stashed


async def test_oidc_login_404_when_disabled(client, monkeypatch):
    monkeypatch.setattr(settings, "OIDC_ISSUER", None)
    res = await client.get("/api/auth/oidc/login")
    assert res.status_code == 404
    assert res.json()["error"]["code"] == "not_found"
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `./venv/bin/pytest tests/test_oidc.py -v`
Expected: the two new tests FAIL with 404 responses that don't match (route doesn't exist yet → FastAPI's default 404 has no `error` envelope; the redirect test gets 404 instead of 302).

- [ ] **Step 4: Add the protocol helpers to the service**

In `backend/app/services/oidc.py`, replace the import block with:

```python
import base64
import json
import secrets
from urllib.parse import urlencode

import httpx
from authlib.oauth2.rfc7636 import create_s256_code_challenge
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models import User
```

Then add, between `class OidcError` and the account-linking section:

```python
# --- provider metadata (lazy, cached — the app must boot while the IdP is down) --

_metadata: dict | None = None
_keyset = None            # JWKS, cached by Task 5's validate_id_token


async def _discovery() -> dict:
    global _metadata
    if _metadata is None:
        url = settings.OIDC_ISSUER.rstrip("/") + "/.well-known/openid-configuration"
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                resp = await client.get(url)
                resp.raise_for_status()
                _metadata = resp.json()
        except (httpx.HTTPError, ValueError) as exc:
            raise OidcError(f"OIDC discovery failed: {exc}")
    return _metadata


# --- one login attempt's short-lived secrets (live in the flow cookie) ----------

def new_flow() -> dict:
    return {
        "state": secrets.token_urlsafe(24),     # CSRF binding for the redirect flow
        "nonce": secrets.token_urlsafe(24),     # binds the ID token to this attempt
        "verifier": secrets.token_urlsafe(48),  # PKCE
    }


def pack_flow(flow: dict) -> str:
    """Cookie-safe encoding — JSON's quotes/braces are hostile to cookie values."""
    return base64.urlsafe_b64encode(json.dumps(flow).encode()).decode()


def unpack_flow(raw: str) -> dict:
    try:
        return json.loads(base64.urlsafe_b64decode(raw.encode()))
    except (ValueError, UnicodeDecodeError):
        raise OidcError("unreadable flow cookie")


async def build_authorize_url(redirect_uri: str, flow: dict) -> str:
    meta = await _discovery()
    if "authorization_endpoint" not in meta:
        raise OidcError("discovery document has no authorization_endpoint")
    return meta["authorization_endpoint"] + "?" + urlencode({
        "response_type": "code",
        "client_id": settings.OIDC_CLIENT_ID,
        "redirect_uri": redirect_uri,
        "scope": "openid email profile",
        "state": flow["state"],
        "nonce": flow["nonce"],
        "code_challenge": create_s256_code_challenge(flow["verifier"]),
        "code_challenge_method": "S256",
    })
```

- [ ] **Step 5: Add the login route**

In `backend/app/routers/auth.py`: add `import logging` to the stdlib imports, `from fastapi.responses import RedirectResponse` under the fastapi import, and `from app.services import oidc` with the app imports. Then, after the `_start_session` helper, add:

```python
# --- SSO (OIDC) ---------------------------------------------------------------

log = logging.getLogger(__name__)

FLOW_COOKIE = "snagr_oidc_flow"   # carries state+nonce+PKCE verifier between the two hops
FLOW_PATH = "/api/auth/oidc"


def _redirect_uri(request: Request) -> str:
    # behind a proxy the request-derived host can be wrong — the setting overrides
    return settings.OIDC_REDIRECT_URI or str(request.url_for("oidc_callback"))


def _sso_failed() -> RedirectResponse:
    """Every failure looks the same to the browser; details go to the log."""
    response = RedirectResponse("/login?error=sso_failed", status_code=302)
    response.delete_cookie(FLOW_COOKIE, path=FLOW_PATH)
    return response


@router.get("/oidc/login")
async def oidc_login(request: Request):
    """Kick off SSO: stash the flow secrets in a cookie, bounce to the IdP."""
    if not settings.oidc_enabled:
        raise err(404, "not_found", "SSO is not configured")
    flow = oidc.new_flow()
    try:
        url = await oidc.build_authorize_url(_redirect_uri(request), flow)
    except oidc.OidcError as exc:
        log.warning("OIDC login redirect failed: %s", exc)
        return _sso_failed()
    response = RedirectResponse(url, status_code=302)
    response.set_cookie(FLOW_COOKIE, oidc.pack_flow(flow), max_age=600, httponly=True,
                        samesite="lax", secure=settings.cookie_secure, path=FLOW_PATH)
    return response
```

`_redirect_uri` resolves the route name `oidc_callback` via `url_for`, so that route must exist for the login route to work. Add it now as a fail-closed placeholder (Task 5 fills it in):

```python
@router.get("/oidc/callback", name="oidc_callback")
async def oidc_callback(request: Request, db: AsyncSession = Depends(get_db)):
    return _sso_failed()    # implemented in the next task
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `./venv/bin/pytest tests/test_oidc.py -v`
Expected: PASS (9 tests).

- [ ] **Step 7: Commit**

```bash
git add backend/requirements.txt backend/app/services/oidc.py backend/app/routers/auth.py backend/tests/test_oidc.py
git commit -m "feat(oidc): discovery, PKCE flow helpers, /api/auth/oidc/login"
```

---

### Task 5: Token exchange, ID-token validation, `GET /api/auth/oidc/callback`

**Files:**
- Modify: `backend/app/services/oidc.py`
- Modify: `backend/app/routers/auth.py` (fill in the placeholder callback)
- Test: `backend/tests/test_oidc.py`

**Interfaces:**
- Consumes: everything from Tasks 3–4 (`unpack_flow`, `exchange` caches, `resolve_oidc_user`, `_start_session`, `FLOW_COOKIE`, `_sso_failed`).
- Produces (in `app.services.oidc`): `async exchange_code(code: str, redirect_uri: str, verifier: str) -> dict` (token response incl. `id_token`) and `async validate_id_token(id_token: str, nonce: str) -> dict` (verified claims). Tests monkeypatch exactly these two names on the `oidc` module.

- [ ] **Step 1: Write the failing tests**

Append to `backend/tests/test_oidc.py` (no new imports needed — the helpers reuse `oidc.pack_flow`):

```python
# --- GET /api/auth/oidc/callback -------------------------------------------------

def _stub_idp(monkeypatch, claims):
    """Replace the two network-touching service fns; the rest runs for real."""
    async def fake_exchange(code, redirect_uri, verifier):
        return {"id_token": "stub-id-token"}
    async def fake_validate(id_token, nonce):
        return claims
    monkeypatch.setattr(oidc, "exchange_code", fake_exchange)
    monkeypatch.setattr(oidc, "validate_id_token", fake_validate)


def _set_flow_cookie(client, flow):
    client.cookies.set("snagr_oidc_flow", oidc.pack_flow(flow),
                       domain="test", path="/api/auth/oidc")


async def _sso_login(client, monkeypatch, claims=CLAIMS):
    """Drive a full (stubbed-IdP) SSO sign-in on `client`; returns the response."""
    _stub_idp(monkeypatch, claims)
    flow = {"state": "st-1", "nonce": "n-1", "verifier": "v-1"}
    _set_flow_cookie(client, flow)
    return await client.get("/api/auth/oidc/callback",
                            params={"code": "c-1", "state": "st-1"})


async def test_callback_signs_in_and_creates_user(client, monkeypatch):
    res = await _sso_login(client, monkeypatch)
    assert res.status_code == 302
    assert res.headers["location"] == "/"
    assert "snagr_access" in res.cookies and "snagr_refresh" in res.cookies
    me = await client.get("/api/auth/me")
    assert me.status_code == 200
    assert me.json()["email"] == "sso@example.com"


async def test_callback_marries_existing_account(client, monkeypatch):
    # a password user registers first...
    reg = await client.post("/api/auth/register",
                            json={"email": "sso@example.com", "password": "hunter2hunter2"},
                            headers={"X-Snagr-Csrf": "1"})
    uid = reg.json()["user"]["id"]
    await client.post("/api/auth/logout", headers={"X-Snagr-Csrf": "1"})
    # ...then signs in via SSO with the same (verified) email -> same account
    await _sso_login(client, monkeypatch)
    me = await client.get("/api/auth/me")
    assert me.json()["id"] == uid


async def test_callback_rejects_state_mismatch(client, monkeypatch):
    _stub_idp(monkeypatch, CLAIMS)
    _set_flow_cookie(client, {"state": "st-1", "nonce": "n-1", "verifier": "v-1"})
    res = await client.get("/api/auth/oidc/callback",
                           params={"code": "c-1", "state": "EVIL"})
    assert res.status_code == 302
    assert res.headers["location"] == "/login?error=sso_failed"
    assert "snagr_access" not in res.cookies


async def test_callback_rejects_missing_flow_cookie(client, monkeypatch):
    _stub_idp(monkeypatch, CLAIMS)
    res = await client.get("/api/auth/oidc/callback",
                           params={"code": "c-1", "state": "st-1"})
    assert res.headers["location"] == "/login?error=sso_failed"


async def test_callback_rejects_idp_error_param(client, monkeypatch):
    _stub_idp(monkeypatch, CLAIMS)
    _set_flow_cookie(client, {"state": "st-1", "nonce": "n-1", "verifier": "v-1"})
    res = await client.get("/api/auth/oidc/callback",
                           params={"error": "access_denied", "state": "st-1", "code": "x"})
    assert res.headers["location"] == "/login?error=sso_failed"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `./venv/bin/pytest tests/test_oidc.py -v`
Expected: the three rejection tests PASS already (placeholder always fails closed); `test_callback_signs_in_and_creates_user` and `test_callback_marries_existing_account` FAIL (redirected to `/login?error=sso_failed`, no cookies). That asymmetry is correct.

- [ ] **Step 3: Add exchange + validation to the service**

In `backend/app/services/oidc.py`, extend the imports:

```python
from authlib.integrations.httpx_client import AsyncOAuth2Client
from authlib.jose import JsonWebKey, JsonWebToken
from authlib.jose.errors import JoseError
```

Add after `build_authorize_url`:

```python
async def _jwks():
    global _keyset
    if _keyset is None:
        meta = await _discovery()
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                resp = await client.get(meta["jwks_uri"])
                resp.raise_for_status()
                _keyset = JsonWebKey.import_key_set(resp.json())
        except (httpx.HTTPError, KeyError, ValueError) as exc:
            raise OidcError(f"JWKS fetch failed: {exc}")
    return _keyset


async def exchange_code(code: str, redirect_uri: str, verifier: str) -> dict:
    """Swap the authorization code for tokens at the IdP's token endpoint."""
    meta = await _discovery()
    try:
        async with AsyncOAuth2Client(
            client_id=settings.OIDC_CLIENT_ID,
            client_secret=settings.OIDC_CLIENT_SECRET,
            redirect_uri=redirect_uri,
        ) as client:
            token = await client.fetch_token(
                meta["token_endpoint"],
                grant_type="authorization_code",
                code=code,
                code_verifier=verifier,
            )
    except Exception as exc:   # authlib raises a small zoo; every one means "failed"
        raise OidcError(f"code exchange failed: {exc}")
    if "id_token" not in token:
        raise OidcError("token response has no id_token")
    return token


async def validate_id_token(id_token: str, nonce: str) -> dict:
    """Verify signature (JWKS), issuer, audience, expiry, nonce -> claims."""
    global _keyset
    meta = await _discovery()
    try:
        claims = JsonWebToken(["RS256", "ES256"]).decode(
            id_token, await _jwks(),
            claims_options={
                "iss": {"essential": True, "value": meta["issuer"]},
                "aud": {"essential": True, "value": settings.OIDC_CLIENT_ID},
            },
        )
        claims.validate()
    except JoseError as exc:
        _keyset = None      # maybe the IdP rotated keys — refetch on the next attempt
        raise OidcError(f"id_token validation failed: {exc}")
    if claims.get("nonce") != nonce:
        raise OidcError("nonce mismatch")
    return dict(claims)
```

- [ ] **Step 4: Fill in the callback route**

In `backend/app/routers/auth.py`, add `import hmac` to the stdlib imports and replace the placeholder callback with:

```python
@router.get("/oidc/callback", name="oidc_callback")
async def oidc_callback(request: Request, db: AsyncSession = Depends(get_db)):
    """The IdP sent the browser back: verify state, trade the code for an ID
    token, resolve the local user, and start a completely normal session."""
    if not settings.oidc_enabled:
        return _sso_failed()
    raw = request.cookies.get(FLOW_COOKIE)
    code = request.query_params.get("code")
    state = request.query_params.get("state")
    if not raw or not code or not state or request.query_params.get("error"):
        return _sso_failed()
    try:
        flow = oidc.unpack_flow(raw)
        if not hmac.compare_digest(state.encode(), str(flow.get("state", "")).encode()):
            raise oidc.OidcError("state mismatch")
        token = await oidc.exchange_code(code, _redirect_uri(request), flow["verifier"])
        claims = await oidc.validate_id_token(token["id_token"], flow["nonce"])
        user = await oidc.resolve_oidc_user(db, claims)
    except (oidc.OidcError, KeyError) as exc:
        log.warning("OIDC callback failed: %s", exc)
        return _sso_failed()
    response = RedirectResponse("/", status_code=302)
    response.delete_cookie(FLOW_COOKIE, path=FLOW_PATH)
    await _start_session(db, response, user)
    await db.commit()
    return response
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `./venv/bin/pytest tests/test_oidc.py -v`
Expected: PASS (14 tests).

- [ ] **Step 6: Full suite green**

Run: `./venv/bin/pytest`
Expected: all pass.

- [ ] **Step 7: Commit**

```bash
git add backend/app/services/oidc.py backend/app/routers/auth.py backend/tests/test_oidc.py
git commit -m "feat(oidc): code exchange, ID-token validation, /api/auth/oidc/callback"
```

---

### Task 6: Clear password-change error for SSO-only accounts

**Files:**
- Modify: `backend/app/routers/me.py:39-41`
- Test: `backend/tests/test_oidc.py`

**Interfaces:**
- Consumes: `_sso_login` test helper (Task 5); existing `err()` envelope.
- Produces: no new interfaces — behavior-only. `POST /api/me/password` for a `password_hash IS NULL` user returns the existing 422 `invalid_password` shape with an SSO-specific message.

- [ ] **Step 1: Write the failing test**

Append to `backend/tests/test_oidc.py`:

```python
# --- SSO-only accounts and the password form -------------------------------------

async def test_password_change_blocked_for_sso_user(client, monkeypatch):
    await _sso_login(client, monkeypatch)     # auto-created, password_hash NULL
    res = await client.post("/api/me/password",
                            json={"current_password": "x", "new_password": "y" * 10},
                            headers={"X-Snagr-Csrf": "1"})
    assert res.status_code == 422
    assert res.json()["error"]["fields"]["current_password"] == "This account signs in with SSO"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `./venv/bin/pytest tests/test_oidc.py::test_password_change_blocked_for_sso_user -v`
Expected: FAIL — message is `"Current password is incorrect"` (the current NULL-hash fallthrough).

- [ ] **Step 3: Split the guard in `change_password`**

In `backend/app/routers/me.py`, replace the two-condition guard:

```python
    # NULL password_hash (invite created, never set) can never match — same 422
    if user.password_hash is None or not verify_password(body.current_password, user.password_hash):
        raise err(422, "invalid_password", "Current password is incorrect",
                  fields={"current_password": "Current password is incorrect"})
```

with:

```python
    if user.password_hash is None:   # SSO-provisioned account — no password to change
        raise err(422, "invalid_password", "This account signs in with SSO",
                  fields={"current_password": "This account signs in with SSO"})
    if not verify_password(body.current_password, user.password_hash):
        raise err(422, "invalid_password", "Current password is incorrect",
                  fields={"current_password": "Current password is incorrect"})
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `./venv/bin/pytest`
Expected: all pass (including the existing `test_password_change`, which covers the wrong-password branch).

- [ ] **Step 5: Commit**

```bash
git add backend/app/routers/me.py backend/tests/test_oidc.py
git commit -m "feat(oidc): SSO-specific message when changing a nonexistent password"
```

---

### Task 7: Login page — SSO button + failure banner

**Files:**
- Modify: `frontend/src/components/ui/button.tsx` (export `buttonVariants`)
- Modify: `frontend/src/features/auth/LoginPage.tsx`

**Interfaces:**
- Consumes: `InstanceInfo.oidc_provider_name` (Task 2) via the existing `useInstance()` hook; backend routes from Tasks 4–5.
- Produces: nothing downstream — this is the last task.

- [ ] **Step 1: Export the button styles**

In `frontend/src/components/ui/button.tsx:5`, change `const buttonVariants = cva(` to `export const buttonVariants = cva(` — the SSO control must be a real `<a>` (top-level navigation), styled like a button.

- [ ] **Step 2: Add the SSO button and error banner**

In `frontend/src/features/auth/LoginPage.tsx`:

Add to the imports:

```tsx
import { useSearchParams } from 'react-router-dom'
import { buttonVariants } from '@/components/ui/button'
import { cn } from '@/lib/cn'
```

(`useSearchParams` merges into the existing `react-router-dom` import; `buttonVariants` merges into the existing `Button` import line.)

Inside the component, under the existing `useState` lines, add:

```tsx
  const [searchParams] = useSearchParams()
```

Extend the `errorMessage` chain so an SSO failure shows in the same `role="alert"` box:

```tsx
  const errorMessage =
    login.error instanceof ApiError
      ? login.error.message
      : login.error
        ? 'Something went wrong — try again'
        : searchParams.get('error') === 'sso_failed'
          ? 'SSO sign-in failed — try again or use your password'
          : null
```

After the closing `</form>` tag and before the `{instance?.registration_open ...}` block, add:

```tsx
      {instance?.oidc_provider_name ? (
        <div className="mt-4">
          <div className="flex items-center gap-2">
            <span className="h-px flex-1 bg-hairline" />
            <span className="text-xs text-ink-3">or</span>
            <span className="h-px flex-1 bg-hairline" />
          </div>
          <a
            href="/api/auth/oidc/login"
            className={cn(buttonVariants({ variant: 'default' }), 'mt-3 w-full')}
          >
            Sign in with {instance.oidc_provider_name}
          </a>
        </div>
      ) : null}
```

(A plain `<a href>` — not a fetch — because the whole flow is browser navigation; middle-click and history behave correctly.)

- [ ] **Step 3: Build + lint**

Run (from `frontend/`):

```bash
npm run build
npm run lint
```

Expected: both succeed.

- [ ] **Step 4: Verify at the browser surface**

Use the **`frontend:verify`** skill (per CLAUDE.md, that's the tool for real-browser verification). Minimum checks: with mocks on, the login page renders with NO SSO button (mock returns `oidc_provider_name: null`); navigating to `/login?error=sso_failed` shows the failure banner.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/components/ui/button.tsx frontend/src/features/auth/LoginPage.tsx
git commit -m "feat(oidc): SSO sign-in button + failure banner on the login page"
```

---

## Not in this plan (spec's "out of scope")

Admin-UI settings page, Authentik-group→role mapping, RP-initiated logout, and IdP→local email sync are all explicitly v2 — do not add them.

## End-to-end smoke test (manual, after all tasks)

Against a real Authentik: create an OAuth2/OIDC provider + application in Authentik (redirect URL `http://<host>:8000/api/auth/oidc/callback`), set the four `OIDC_*` vars in `backend/.env`, restart the backend, and click "Sign in with Authentik" from the login page: you should land on the dashboard signed in, and `users` should show the new row with `oidc_sub` set (or your existing row married to it).
