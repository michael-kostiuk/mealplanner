from app.auth.pin import hash_pin, verify_pin
from app.auth.rate_limit import LoginLimiter


class FakeClock:
    def __init__(self, now: float = 0.0):
        self.now = now

    def __call__(self) -> float:
        return self.now


def make_limiter():
    clock = FakeClock()
    return clock, LoginLimiter(clock=clock)


def test_verify_pin_roundtrip():
    h = hash_pin("1234")
    assert verify_pin("1234", h) is True
    assert verify_pin("0000", h) is False
    assert verify_pin("1234", "garbage") is False


def test_three_failures_lock_one_hour():
    _, limiter = make_limiter()
    limiter.record_failure()
    limiter.record_failure()
    assert limiter.locked_for() == 0
    limiter.record_failure()
    assert limiter.locked_for() == 3600


def test_backoff_doubles():
    clock, limiter = make_limiter()
    for _ in range(3):
        limiter.record_failure()
    assert limiter.locked_for() == 3600
    clock.now = 3600
    assert limiter.locked_for() == 0
    limiter.record_failure()
    assert limiter.locked_for() == 7200
    clock.now = 3600 + 7200
    limiter.record_failure()
    assert limiter.locked_for() == 14400


def test_failures_outside_window_dont_count():
    clock, limiter = make_limiter()
    limiter.record_failure()
    clock.now = 1
    limiter.record_failure()
    clock.now = 3700
    limiter.record_failure()
    assert limiter.locked_for() == 0


def test_success_resets():
    clock, limiter = make_limiter()
    for _ in range(3):
        limiter.record_failure()
    clock.now = 3600
    limiter.record_success()
    limiter.record_failure()
    limiter.record_failure()
    assert limiter.locked_for() == 0
