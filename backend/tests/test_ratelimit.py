"""core/ratelimit.AttemptLimit on its own: the sliding window and the sweep.
The routes that use it are covered in test_auth_flow.py."""

from app.core import ratelimit
from app.core.ratelimit import AttemptLimit


class _Clock:
    """A time.monotonic stand-in the test moves by hand."""

    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


def _clock(monkeypatch) -> _Clock:
    clock = _Clock()
    monkeypatch.setattr(ratelimit.time, "monotonic", clock)
    return clock


def test_refuses_at_the_limit_until_the_oldest_attempt_leaves_the_window(monkeypatch):
    clock = _clock(monkeypatch)
    limit = AttemptLimit(limit=3, window=60)
    for _ in range(2):
        limit.record("k")
        clock.now += 10
    assert limit.retry_after("k") == 0
    limit.record("k")  # attempts at 1000, 1010, 1020
    assert limit.retry_after("k") == 40  # the one at 1000 leaves at 1060
    assert limit.retry_after("other") == 0

    clock.now = 1060
    assert limit.retry_after("k") == 0
    limit.record("k")  # now 1010, 1020, 1060
    assert limit.retry_after("k") == 10


def test_sweep_drops_keys_whose_window_has_passed(monkeypatch):
    clock = _clock(monkeypatch)
    monkeypatch.setattr(ratelimit, "_SWEEP_FLOOR", 4)
    limit = AttemptLimit(limit=1, window=60)
    for n in range(3):
        limit.record(f"old{n}")
    clock.now += 61
    limit.record("new")  # the fourth key triggers a sweep
    assert list(limit._attempts) == ["new"]
