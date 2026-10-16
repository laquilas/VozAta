from __future__ import annotations

import numpy as np
import pytest

from vozata.audio.levels import SILENCE_DB, rms_db


def test_full_scale_square_wave_is_zero_db() -> None:
    samples = np.array([1.0, -1.0, 1.0, -1.0], dtype=np.float32)

    assert rms_db(samples) == pytest.approx(0.0)


def test_half_amplitude_is_about_minus_six_db() -> None:
    samples = np.full(100, 0.5, dtype=np.float32)

    assert rms_db(samples) == pytest.approx(-6.0206, abs=1e-3)


@pytest.mark.parametrize(
    "samples", [np.zeros(10, dtype=np.float32), np.array([], dtype=np.float32)]
)
def test_silence_and_empty_input_hit_the_floor(samples: np.ndarray) -> None:
    assert rms_db(samples) == SILENCE_DB == -90.0


def test_very_quiet_signal_is_clamped_to_the_floor() -> None:
    assert rms_db(np.full(10, 1e-7, dtype=np.float32)) == -90.0
