"""Pairing codes of the worker (phase 47): a short code shown on the worker PC gives the token."""

from __future__ import annotations

import hmac
import secrets
import threading
import time
from collections.abc import Callable
from enum import StrEnum

VALID_SECONDS = 300.0
MAX_FAILURES = 5
LOCK_SECONDS = 60.0


class PairResult(StrEnum):
    OK = "ok"
    REFUSED = "refused"
    LOCKED = "locked"


def _six_digits() -> str:
    return f"{secrets.randbelow(10**6):06d}"


class PairingCodes:
    """One 6-digit code at a time, valid `VALID_SECONDS`; a used code is replaced. After
    `MAX_FAILURES` wrong codes pairing is locked for `LOCK_SECONDS` and the code is replaced, so
    a guesser on the network gets at most 5 tries per minute against a 1-in-a-million code."""

    def __init__(
        self,
        clock: Callable[[], float] = time.monotonic,
        new_code: Callable[[], str] = _six_digits,
    ) -> None:
        self._clock = clock
        self._new_code = new_code
        self._lock = threading.Lock()
        self._code: str | None = None
        self._expires = 0.0
        self._failures = 0
        self._locked_until = 0.0

    def current(self) -> tuple[str, float]:
        """The code and the seconds it stays valid."""
        with self._lock:
            now = self._clock()
            code = self._valid(now)
            return code, self._expires - now

    def check(self, given: str) -> PairResult:
        with self._lock:
            now = self._clock()
            if now < self._locked_until:
                return PairResult.LOCKED
            code = self._valid(now)
            if hmac.compare_digest(given.strip().encode(), code.encode()):
                self._failures = 0
                self._code = None  # used
                return PairResult.OK
            self._failures += 1
            if self._failures >= MAX_FAILURES:
                self._failures = 0
                self._locked_until = now + LOCK_SECONDS
                self._code = None
            return PairResult.REFUSED

    def _valid(self, now: float) -> str:
        if self._code is None or now >= self._expires:
            self._code = self._new_code()
            self._expires = now + VALID_SECONDS
        return self._code
