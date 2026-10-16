"""Contract every `Transcriber` must honour (architecture §3, Liskov).

Reuse from a provider's tests: `check_transcriber_contract(transcriber, speech, language)`.
"""

from __future__ import annotations

import numpy as np

from vozata.ports import Transcriber

SAMPLE_RATE = 16000


def check_transcriber_contract(
    transcriber: Transcriber, speech: np.ndarray, language: str | None
) -> None:
    """Silence yields an empty result (never raises); speech yields words whose timestamps are
    relative to the given audio and whose probabilities lie in [0, 1]."""
    assert isinstance(transcriber, Transcriber)

    silent = transcriber.transcribe(np.zeros(2 * SAMPLE_RATE, dtype=np.float32), language)
    assert silent.words == ()

    result = transcriber.transcribe(speech, language)
    duration = len(speech) / SAMPLE_RATE
    assert result.words, "speech produced no words"
    for word in result.words:
        assert word.text.strip()
        assert 0.0 <= word.start <= word.end <= duration + 0.5
        assert 0.0 <= word.probability <= 1.0
