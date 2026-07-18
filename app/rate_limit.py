"""Thread-safe, in-memory abuse controls for the single-label verifier."""

from __future__ import annotations

import ipaddress
import math
import os
import threading
import time
from collections import OrderedDict, deque
from collections.abc import Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from fastapi import Request

MINUTE_SECONDS = 60.0
HOUR_SECONDS = 3_600.0
BUSY_RETRY_SECONDS = 5
MAX_TRACKED_CLIENTS = 10_000

_clock = time.monotonic


def _positive_env_int(name: str, default: int) -> int:
    raw_value = os.environ.get(name, str(default))
    try:
        value = int(raw_value)
    except ValueError as exc:
        raise RuntimeError(f"{name} must be a positive integer") from exc
    if value <= 0:
        raise RuntimeError(f"{name} must be a positive integer")
    return value


@dataclass(frozen=True)
class RateLimitSettings:
    per_minute: int = 5
    per_hour: int = 30
    global_per_hour: int = 100
    max_concurrent: int = 2

    @classmethod
    def from_env(cls) -> RateLimitSettings:
        return cls(
            per_minute=_positive_env_int("VERIFY_RATE_LIMIT_PER_MINUTE", 5),
            per_hour=_positive_env_int("VERIFY_RATE_LIMIT_PER_HOUR", 30),
            global_per_hour=_positive_env_int(
                "VERIFY_GLOBAL_RATE_LIMIT_PER_HOUR", 100
            ),
            max_concurrent=_positive_env_int("VERIFY_MAX_CONCURRENT", 2),
        )


@dataclass(frozen=True)
class RateLimitDecision:
    allowed: bool
    retry_after: int = 0
    scope: str = "-"
    code: str = "-"


@dataclass(frozen=True)
class RateLimitSnapshot:
    tracked_clients: int
    global_attempts: int
    active_verifications: int


class VerificationLease:
    """Idempotent lease for one active, globally-budgeted verification."""

    def __init__(self, limiter: VerifyRateLimiter) -> None:
        self._limiter = limiter
        self._released = False
        self._release_lock = threading.Lock()

    def release(self) -> None:
        with self._release_lock:
            if self._released:
                return
            self._released = True
        self._limiter._release_verification()


class VerifyRateLimiter:
    """Sliding per-client/hourly limits plus global call and concurrency caps."""

    def __init__(
        self,
        settings: RateLimitSettings,
        *,
        clock: Callable[[], float] = _clock,
        max_tracked_clients: int = MAX_TRACKED_CLIENTS,
    ) -> None:
        if max_tracked_clients <= 0:
            raise ValueError("max_tracked_clients must be positive")
        self.settings = settings
        self._clock = clock
        self._max_tracked_clients = max_tracked_clients
        self._client_attempts: OrderedDict[str, deque[float]] = OrderedDict()
        self._global_attempts: deque[float] = deque()
        self._active_verifications = 0
        self._lock = threading.Lock()

    def check_client(self, client_id: str) -> RateLimitDecision:
        now = self._clock()
        with self._lock:
            attempts = self._client_attempts.get(client_id)
            if attempts is None:
                self._prune_expired_clients_locked(now)
                if len(self._client_attempts) >= self._max_tracked_clients:
                    earliest_expiry = min(
                        client_attempts[0] + HOUR_SECONDS
                        for client_attempts in self._client_attempts.values()
                    )
                    return RateLimitDecision(
                        allowed=False,
                        retry_after=self._retry_after(earliest_expiry, now),
                        scope="client_capacity",
                        code="RATE_LIMITED",
                    )
                attempts = deque()
                self._client_attempts[client_id] = attempts
            else:
                self._client_attempts.move_to_end(client_id)

            self._prune_deque(attempts, now - HOUR_SECONDS)
            retry_after = self._client_retry_after_locked(attempts, now)
            if retry_after:
                return RateLimitDecision(
                    allowed=False,
                    retry_after=retry_after,
                    scope="client",
                    code="RATE_LIMITED",
                )

            attempts.append(now)
            return RateLimitDecision(allowed=True)

    def acquire_verification(
        self,
    ) -> tuple[RateLimitDecision, VerificationLease | None]:
        now = self._clock()
        with self._lock:
            self._prune_deque(self._global_attempts, now - HOUR_SECONDS)
            if len(self._global_attempts) >= self.settings.global_per_hour:
                retry_after = self._retry_after(
                    self._global_attempts[0] + HOUR_SECONDS,
                    now,
                )
                return (
                    RateLimitDecision(
                        allowed=False,
                        retry_after=retry_after,
                        scope="global",
                        code="RATE_LIMITED",
                    ),
                    None,
                )

            if self._active_verifications >= self.settings.max_concurrent:
                return (
                    RateLimitDecision(
                        allowed=False,
                        retry_after=BUSY_RETRY_SECONDS,
                        scope="concurrency",
                        code="VERIFICATION_BUSY",
                    ),
                    None,
                )

            self._global_attempts.append(now)
            self._active_verifications += 1

        return RateLimitDecision(allowed=True), VerificationLease(self)

    def snapshot(self) -> RateLimitSnapshot:
        now = self._clock()
        with self._lock:
            self._prune_expired_clients_locked(now)
            self._prune_deque(self._global_attempts, now - HOUR_SECONDS)
            return RateLimitSnapshot(
                tracked_clients=len(self._client_attempts),
                global_attempts=len(self._global_attempts),
                active_verifications=self._active_verifications,
            )

    def reset(self) -> None:
        with self._lock:
            self._client_attempts.clear()
            self._global_attempts.clear()
            self._active_verifications = 0

    def _release_verification(self) -> None:
        with self._lock:
            if self._active_verifications <= 0:
                raise RuntimeError("verification lease released without an active request")
            self._active_verifications -= 1

    def _client_retry_after_locked(
        self,
        attempts: deque[float],
        now: float,
    ) -> int:
        retry_deadlines: list[float] = []
        if len(attempts) >= self.settings.per_hour:
            retry_deadlines.append(attempts[0] + HOUR_SECONDS)

        minute_attempts = [
            timestamp for timestamp in attempts if timestamp > now - MINUTE_SECONDS
        ]
        if len(minute_attempts) >= self.settings.per_minute:
            retry_deadlines.append(minute_attempts[0] + MINUTE_SECONDS)

        if not retry_deadlines:
            return 0
        return self._retry_after(max(retry_deadlines), now)

    def _prune_expired_clients_locked(self, now: float) -> None:
        expired_clients: list[str] = []
        cutoff = now - HOUR_SECONDS
        for client_id, attempts in self._client_attempts.items():
            self._prune_deque(attempts, cutoff)
            if not attempts:
                expired_clients.append(client_id)
        for client_id in expired_clients:
            del self._client_attempts[client_id]

    @staticmethod
    def _prune_deque(values: deque[float], cutoff: float) -> None:
        while values and values[0] <= cutoff:
            values.popleft()

    @staticmethod
    def _retry_after(deadline: float, now: float) -> int:
        return max(1, math.ceil(deadline - now))


def client_identifier(request: Request) -> str:
    """Return Railway's normalized client IP without logging or exposing it."""

    real_ip = request.headers.get("x-real-ip", "").strip()
    if real_ip:
        try:
            return str(ipaddress.ip_address(real_ip))
        except ValueError:
            pass

    fallback = request.client.host if request.client else "unknown"
    try:
        return str(ipaddress.ip_address(fallback))
    except ValueError:
        return fallback or "unknown"
