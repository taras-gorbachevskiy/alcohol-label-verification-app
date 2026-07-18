from __future__ import annotations

import pytest

from app.rate_limit import RateLimitSettings, VerifyRateLimiter


class MutableClock:
    def __init__(self, value: float = 0.0) -> None:
        self.value = value

    def __call__(self) -> float:
        return self.value

    def advance(self, seconds: float) -> None:
        self.value += seconds


def _settings(**updates: int) -> RateLimitSettings:
    values = {
        "per_minute": 5,
        "per_hour": 30,
        "global_per_hour": 100,
        "max_concurrent": 2,
    }
    values.update(updates)
    return RateLimitSettings(**values)


def test_client_minute_limit_has_deterministic_retry_and_recovers() -> None:
    clock = MutableClock(100.0)
    limiter = VerifyRateLimiter(_settings(), clock=clock)

    assert all(limiter.check_client("203.0.113.10").allowed for _ in range(5))
    denied = limiter.check_client("203.0.113.10")

    assert not denied.allowed
    assert denied.code == "RATE_LIMITED"
    assert denied.scope == "client"
    assert denied.retry_after == 60

    clock.advance(59.1)
    assert limiter.check_client("203.0.113.10").retry_after == 1
    clock.advance(0.9)
    assert limiter.check_client("203.0.113.10").allowed


def test_client_hour_limit_uses_a_rolling_window() -> None:
    clock = MutableClock()
    limiter = VerifyRateLimiter(
        _settings(per_minute=100, per_hour=3),
        clock=clock,
    )

    for _ in range(3):
        assert limiter.check_client("203.0.113.11").allowed
        clock.advance(61)

    denied = limiter.check_client("203.0.113.11")
    assert not denied.allowed
    assert denied.retry_after == 3_417

    clock.advance(3_417)
    assert limiter.check_client("203.0.113.11").allowed


def test_client_limits_are_independent() -> None:
    limiter = VerifyRateLimiter(_settings(per_minute=1))

    assert limiter.check_client("203.0.113.12").allowed
    assert not limiter.check_client("203.0.113.12").allowed
    assert limiter.check_client("203.0.113.13").allowed


def test_global_budget_counts_each_acquired_verification_once() -> None:
    clock = MutableClock(50.0)
    limiter = VerifyRateLimiter(_settings(global_per_hour=2), clock=clock)

    for _ in range(2):
        decision, lease = limiter.acquire_verification()
        assert decision.allowed
        assert lease is not None
        lease.release()
        lease.release()

    denied, lease = limiter.acquire_verification()
    assert not denied.allowed
    assert denied.code == "RATE_LIMITED"
    assert denied.scope == "global"
    assert denied.retry_after == 3_600
    assert lease is None
    assert limiter.snapshot().global_attempts == 2

    clock.advance(3_600)
    recovered, recovered_lease = limiter.acquire_verification()
    assert recovered.allowed
    assert recovered_lease is not None
    recovered_lease.release()


def test_concurrency_rejection_does_not_consume_global_budget() -> None:
    limiter = VerifyRateLimiter(_settings(max_concurrent=2))

    first, first_lease = limiter.acquire_verification()
    second, second_lease = limiter.acquire_verification()
    third, third_lease = limiter.acquire_verification()

    assert first.allowed and second.allowed
    assert first_lease is not None and second_lease is not None
    assert not third.allowed
    assert third.code == "VERIFICATION_BUSY"
    assert third.scope == "concurrency"
    assert third.retry_after == 5
    assert third_lease is None
    assert limiter.snapshot().global_attempts == 2

    first_lease.release()
    recovered, recovered_lease = limiter.acquire_verification()
    assert recovered.allowed
    assert recovered_lease is not None
    assert limiter.snapshot().global_attempts == 3

    recovered_lease.release()
    second_lease.release()
    assert limiter.snapshot().active_verifications == 0


def test_client_tracking_is_bounded_and_expired_records_are_pruned() -> None:
    clock = MutableClock()
    limiter = VerifyRateLimiter(
        _settings(),
        clock=clock,
        max_tracked_clients=2,
    )

    assert limiter.check_client("203.0.113.20").allowed
    assert limiter.check_client("203.0.113.21").allowed
    denied = limiter.check_client("203.0.113.22")
    assert not denied.allowed
    assert denied.scope == "client_capacity"
    assert denied.retry_after == 3_600
    assert limiter.snapshot().tracked_clients == 2

    clock.advance(3_600)
    assert limiter.check_client("203.0.113.22").allowed
    assert limiter.snapshot().tracked_clients == 1


@pytest.mark.parametrize("value", ["0", "-1", "not-a-number"])
def test_environment_limits_must_be_positive_integers(
    monkeypatch: pytest.MonkeyPatch,
    value: str,
) -> None:
    monkeypatch.setenv("VERIFY_RATE_LIMIT_PER_MINUTE", value)

    with pytest.raises(RuntimeError, match="VERIFY_RATE_LIMIT_PER_MINUTE"):
        RateLimitSettings.from_env()
