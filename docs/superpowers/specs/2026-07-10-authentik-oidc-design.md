# Authentik / OIDC Login — Design

**Date:** 2026-07-10
**Status:** Approved (pending spec review)

## Goal

Let users sign in to Snagr through Authentik via standard OIDC, alongside the
existing email+password login. Existing local accounts gain SSO by being
"married" to their Authentik identity on first SSO login; new Authentik users
are auto-provisioned.

The integration is **generic OIDC** — Authentik is just the provider we happen
to run. Nothing Authentik-specific is hardcoded.

## Decisions (settled during brainstorming)

| Decision | Choice | Rationale |
|---|---|---|
| Enablement | Env config (`.env`), not an admin UI | Fits `config.py`'s "one place env is read" rule; secret stays next to `JWT_SECRET`; misconfig fails loudly at startup logs; a settings UI is a possible v2 and nothing here blocks it. |
| Unknown Authentik user | Auto-create as `role="user"` | Access control centralizes in Authentik (assign the Snagr app to users/groups there). Snagr's invite system remains for password-only users. |
| Admin role | Managed in Snagr | No group-claim parsing or demotion edge cases. Promote via the existing admin page. Group→role mapping is a possible v2. |
| Password login | Coexists, unchanged | Lockout safety net; SSO-only users simply have `password_hash = NULL`. |

## Key insight

The session layer is untouched. Every existing way of proving identity
(register, login, invite-accept) funnels into `_start_session()` in
`routers/auth.py`, which mints the access-JWT + rotating-refresh cookie pair.
OIDC is a fourth way to prove identity; once the callback resolves a `User`,
it calls the same helper. Refresh rotation, `current_user`, CSRF, and logout
all work with zero changes.

## Configuration (`config.py`)

```python
# SSO (OIDC) — enabled iff ISSUER, CLIENT_ID and CLIENT_SECRET are all set
OIDC_ISSUER: str | None = None         # e.g. https://auth.lan/application/o/snagr/
OIDC_CLIENT_ID: str | None = None
OIDC_CLIENT_SECRET: str | None = None
OIDC_PROVIDER_NAME: str = "SSO"        # login-button label, e.g. "Authentik"
OIDC_REDIRECT_URI: str | None = None   # override when the derived URL is wrong (proxies, dev)
```

The `redirect_uri` defaults to `request.url_for("oidc_callback")`. Behind the
Vite dev proxy or a reverse proxy the backend-derived host can differ from the
browser-facing one, so `OIDC_REDIRECT_URI` overrides it explicitly. Either
way, the URL registered in Authentik is
`https://<public-host>/api/auth/oidc/callback`.

Provider metadata (authorize/token/JWKS URLs) comes from OIDC discovery at
`{OIDC_ISSUER}/.well-known/openid-configuration`, fetched **lazily and
cached** — the backend must still boot when the IdP is down. `.env.example`
gains the four variables, commented out.

## Schema (one Alembic migration)

- `users.oidc_sub: Text | None`, unique index. `# + api` comment per the
  D1 convention. Nullable — password-only users never get one.

No other tables change. The agent's ORM subset (`agent/database.py`) is
unaffected (it does not select this column).

## Backend flow

Two new **GET** routes (browser navigations, not fetches) plus one service.
The routes live in `routers/auth.py` — its docstring promises "the whole login
flow, in one file", and this keeps that promise. The linking logic goes in
`services/oidc.py`.

### `GET /api/auth/oidc/login`

302 to the provider's authorization endpoint with `response_type=code`,
`scope=openid email profile`, PKCE (S256), `state`, and `nonce`. The `state`,
PKCE verifier, and `nonce` are stashed in a short-lived (10 min) httpOnly
cookie — that is the flow's CSRF protection. (`csrf_guard` only applies to
non-GET, so these routes don't interact with the `X-Snagr-Csrf` scheme.)

### `GET /api/auth/oidc/callback?code&state`

1. Verify `state` matches the flow cookie; clear the cookie.
2. Exchange the code via `authlib` (client secret + PKCE verifier).
3. Validate the ID token: signature (JWKS), issuer, audience, nonce, expiry.
4. `resolve_oidc_user(db, claims)` → `User` (below).
5. `_start_session(db, response, user)` → 302 to `/`.

Any failure (user denied consent at the IdP, bad/missing state, exchange or
validation error) → 302 to `/login?error=sso_failed`. Never a JSON error
envelope — the browser is mid-navigation. Details go to the server log.

### `resolve_oidc_user(db, claims)` — `services/oidc.py`

Multi-step logic, so it earns service status per the layer rules:

1. **By subject:** user with `oidc_sub == claims["sub"]` → done.
2. **By email (the marriage):** only if `claims.get("email_verified") is True`,
   look up by email. If found, stamp `oidc_sub` on that row — once. From then
   on rule 1 wins, even if the Authentik email changes later. The
   verified-email guard closes the account-takeover hole where an unverified
   IdP email hijacks an existing local account.
3. **Auto-create:** `email`, `role="user"`, `is_active=True`,
   `email_verified=True`, `password_hash=NULL`, `oidc_sub` set.

Every branch rejects `is_active == False` — deactivation holds even via SSO
(mirrors the check in `deps.current_user`). Rejection surfaces as the
`sso_failed` redirect.

## Frontend contract (designed first, per repo workflow)

- **`types.ts`:** `InstanceInfo` gains `oidc_provider_name: string | null` —
  `null` = SSO disabled. Mirrors the `ntfy_server_url` null-when-unconfigured
  pattern.
- **`handlers.ts`:** mock returns `oidc_provider_name: null` (button hidden in
  mock mode — MSW cannot simulate a cross-site redirect flow).
- **Login page (`pages/auth/`):** when non-null, render
  "Sign in with {oidc_provider_name}" as a plain
  `<a href="/api/auth/oidc/login">`; show an error banner when
  `?error=sso_failed` is in the URL.
- **No `endpoints.ts` additions** — both routes are navigations, not fetches.
- **Backend `schemas/auth.py`:** `InstanceInfo` mirrors the new field;
  `routers/instance.py` derives it from settings.

## Edge behaviors

- **Change-password by an SSO-only user** (`password_hash IS NULL`):
  `POST /api/me/password` returns the existing 422 `validation_error` shape
  with `fields.current_password = "This account signs in with SSO"`. No new
  contract shape; the form just errors.
- **Password login by an SSO-only user:** already rejected safely — `login`
  guards `user.password_hash is None`.
- **Email changed in Authentik after marriage:** `oidc_sub` match wins; local
  email is not auto-synced in v1.
- **Logout:** local only. The Authentik session survives; no RP-initiated
  logout in v1.

## Dependencies

Add `authlib` to `backend/requirements.txt`. It rides on the already-present
`httpx` and handles discovery, PKCE, and JWKS/ID-token validation — no
hand-rolled crypto.

## Testing

Same conftest/throwaway-DB pattern as the rest of the suite; set `OIDC_*` in
test settings.

- **Unit — `resolve_oidc_user`:** sub match; email marry (stamps `oidc_sub`);
  unverified email does *not* marry; auto-create branch; inactive user
  rejected on each branch.
- **Router — `/api/auth/oidc/login`:** 302 to the issuer's authorize URL with
  correct `client_id`, `redirect_uri`, `state`, PKCE challenge; flow cookie
  set. (Discovery stubbed.)
- **Router — `/api/auth/oidc/callback`:** with the token exchange stubbed,
  asserts both auth cookies are set and the response redirects to `/`;
  bad/missing state → redirect to `/login?error=sso_failed` with no cookies.

## Out of scope (possible v2)

- Admin UI for OIDC settings (would generalize into an instance-settings page
  that could also absorb `REGISTRATION_OPEN`).
- Authentik group → Snagr role mapping.
- RP-initiated (single) logout.
- Syncing local email/display fields from the IdP on each login.
