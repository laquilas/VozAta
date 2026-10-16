"""Signal levels for meters (console in phase 05, `level` events in phase 06)."""

from __future__ import annotations

import numpy as np

SILENCE_DB = -90.0


def rms_db(samples: np.ndarray) -> float:
    """RMS level in dBFS, floored at `SILENCE_DB` (also for empty input)."""
    if samples.size == 0:
        return SILENCE_DB
    rms = float(np.sqrt(np.mean(np.square(samples, dtype=np.float64))))
    if rms <= 0.0:
        return SILENCE_DB
    return max(SILENCE_DB, 20.0 * float(np.log10(rms)))
