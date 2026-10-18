"""Diarize a stored session: the system track → a speaker-labelled transcript + speakers."""

from __future__ import annotations

import logging
from collections.abc import Callable

from vozata.diarization.assign import assign_speakers
from vozata.domain import Channel
from vozata.ports import AudioReader, Diarizer, SessionRepository

_log = logging.getLogger(__name__)


def diarize_session(
    store: SessionRepository,
    audio: AudioReader,
    session_id: str,
    diarizer_factory: Callable[[], Diarizer],
    min_speakers: int | None,
    max_speakers: int | None,
) -> int | None:
    """Tag the system segments of the raw transcript with `system:<n>` speakers.

    Returns how many remote speakers were found, or None when the transcript has no system
    segment (the diarizer is then never built). The diarizer is always closed before returning,
    so its GPU memory is free for the minutes. The raw transcript is never rewritten; errors
    propagate. The diarizer gets the system track as a WAV file (`AudioReader.materialize_wav`).
    """
    segments = store.load_raw_transcript(session_id)
    if not any(segment.channel is Channel.SYSTEM for segment in segments):
        _log.info("No system speech in %s; speaker identification skipped", session_id)
        return None
    diarizer = diarizer_factory()
    try:
        wav = audio.materialize_wav(session_id, Channel.SYSTEM)
        turns = diarizer.diarize(wav, min_speakers, max_speakers)
    finally:
        _close(diarizer)
    assigned = assign_speakers(segments, turns)
    speakers = list(
        dict.fromkeys(
            segment.speaker_id
            for segment in sorted(assigned, key=lambda segment: segment.start)
            if segment.speaker_id.startswith(f"{Channel.SYSTEM.value}:")
        )
    )
    store.write_diarized(session_id, assigned)
    store.write_speakers(session_id, speakers)
    return len(speakers)


def _close(diarizer: Diarizer) -> None:
    try:
        diarizer.close()
    except Exception:
        _log.exception("Releasing the diarizer failed")
