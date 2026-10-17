"""Diarize a stored session: `system.wav` → `transcript.diarized.jsonl` + `speakers.json`."""

from __future__ import annotations

import logging
from collections.abc import Callable

from vozata.diarization.assign import assign_speakers
from vozata.domain import Channel
from vozata.ports import Diarizer
from vozata.storage.session_store import SessionStore

_log = logging.getLogger(__name__)


def diarize_session(
    store: SessionStore,
    session_id: str,
    diarizer_factory: Callable[[], Diarizer],
    min_speakers: int | None,
    max_speakers: int | None,
) -> int | None:
    """Tag the system segments of the raw transcript with `system:<n>` speakers.

    Returns how many remote speakers were found, or None when the transcript has no system
    segment (the diarizer is then never built). The diarizer is always closed before returning,
    so its GPU memory is free for the minutes. Raw files are never rewritten; errors propagate.
    """
    segments = store.load_raw_transcript(session_id)
    if not any(segment.channel is Channel.SYSTEM for segment in segments):
        _log.info("No system speech in %s; speaker identification skipped", session_id)
        return None
    diarizer = diarizer_factory()
    try:
        wav = store.paths(session_id).wav(Channel.SYSTEM)
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
