"""Sign-in attempt limits: how many passwords one address, or one account, may
try before the credential routes answer 429 rate_limited.

An attempt counts when it starts, not when it fails: a burst of concurrent
guesses would otherwise all pass the check before the first one failed. A
key over its limit is refused even with the right password — else a guesser
would simply keep going until a 200. The account limit stops a guesser who
rotates addresses; the address limit stops one address trying a few
passwords on every account.

The counts live in this process: a restart forgets them and each replica
counts on its own. That is enough for the job — it turns an online guessing
run from thousands of tries a minute into a handful — and needs nothing a
self-hoster doesn't already run.

The address is request.client.host, which behind a reverse proxy is the
proxy's own until uvicorn trusts it (FORWARDED_ALLOW_IPS, see
backend/.env.example) — until then every visitor shares one address limit.
"""

import math
import time
from collections import deque

from app.core.errors import ApiError, err

_WINDOW = 15 * 60  # seconds

# a sweep drops expired keys once the table reaches this size, then again
# each time it doubles
_SWEEP_FLOOR = 10_000


class AttemptLimit:
    """Refuses a key once it has made `limit` attempts inside the last `window` seconds."""

    def __init__(self, limit: int, window: float = _WINDOW) -> None:
        """Start with no attempts recorded."""
        self.limit = limit
        self.window = window
        # only the newest `limit` attempts matter: the key is refused while
        # the oldest of them is still inside the window
        self._attempts: dict[str, deque[float]] = {}
        self._sweep_at = _SWEEP_FLOOR

    def retry_after(self, key: str) -> int:
        """Whole seconds until `key` may try again; 0 when it may now."""
        attempts = self._attempts.get(key)
        if attempts is None or len(attempts) < self.limit:
            return 0
        return max(0, math.ceil(attempts[0] + self.window - time.monotonic()))

    def record(self, key: str) -> None:
        """Count one attempt by `key`."""
        now = time.monotonic()
        self._attempts.setdefault(key, deque(maxlen=self.limit)).append(now)
        if len(self._attempts) >= self._sweep_at:
            self._sweep(now)

    def clear(self) -> None:
        """Forget every attempt."""
        self._attempts.clear()
        self._sweep_at = _SWEEP_FLOOR

    def _sweep(self, now: float) -> None:
        """Drop keys whose newest attempt has left the window, so a run of
        one-off keys (a guesser trying every email) can't grow the table for
        ever."""
        cutoff = now - self.window
        for key in [k for k, attempts in self._attempts.items() if attempts[-1] <= cutoff]:
            del self._attempts[key]
        self._sweep_at = max(_SWEEP_FLOOR, 2 * len(self._attempts))


# sign-ins per client address, across every account it tries
by_address = AttemptLimit(limit=50)
# sign-ins per account (keyed by lowercased email) from anywhere: logins, and
# a password change checking the current password
by_account = AttemptLimit(limit=10)


def rate_limited(seconds: int) -> ApiError:
    """The 429 for a caller over a limit, saying how long to wait."""
    minutes = math.ceil(seconds / 60)
    return err(
        429,
        "rate_limited",
        f"Too many sign-in attempts — try again in {minutes} minute{'' if minutes == 1 else 's'}",
    )
