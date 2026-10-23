from __future__ import annotations

import itertools

from vozata.worker.pairing import (
    LOCK_SECONDS,
    MAX_FAILURES,
    VALID_SECONDS,
    PairingCodes,
    PairResult,
)


class _Clock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


def _codes() -> tuple[PairingCodes, _Clock]:
    clock = _Clock()
    numbers = itertools.count(1)
    return PairingCodes(clock, lambda: f"{next(numbers):06d}"), clock


def test_a_code_has_six_digits_and_lasts_five_minutes() -> None:
    codes, clock = _codes()

    assert codes.current() == ("000001", VALID_SECONDS)
    clock.now += 100
    assert codes.current() == ("000001", VALID_SECONDS - 100)
    clock.now += VALID_SECONDS
    assert codes.current()[0] == "000002"


def test_the_right_code_pairs_once() -> None:
    codes, _ = _codes()

    assert codes.check("000001") is PairResult.OK
    assert codes.current()[0] == "000002"  # used: the next pairing needs a new code
    assert codes.check("000001") is PairResult.REFUSED


def test_an_expired_code_is_refused() -> None:
    codes, clock = _codes()
    codes.current()
    clock.now += VALID_SECONDS + 1

    assert codes.check("000001") is PairResult.REFUSED


def test_wrong_codes_lock_pairing_for_a_minute_then_a_new_code_works() -> None:
    codes, clock = _codes()
    codes.current()

    results = [codes.check("999999") for _ in range(MAX_FAILURES)]

    assert results == [PairResult.REFUSED] * MAX_FAILURES
    assert codes.check(codes.current()[0]) is PairResult.LOCKED
    clock.now += LOCK_SECONDS
    code = codes.current()[0]
    assert code != "000001"  # guessing again starts against a new code
    assert codes.check(code) is PairResult.OK


def test_spaces_around_the_typed_code_are_ignored() -> None:
    codes, _ = _codes()

    assert codes.check(" 000001 ") is PairResult.OK
