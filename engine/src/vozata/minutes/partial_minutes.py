"""Minutes of part of a meeting (phase 48): what was said so far, or a time range."""

from __future__ import annotations

import threading
import uuid
from collections.abc import Callable, Sequence
from datetime import datetime

from vozata.domain import ConversationLanguage, PartialMinutes, TranscriptSegment
from vozata.formatting import format_timestamp
from vozata.labels import SpeakerLabeler
from vozata.minutes.session_minutes import (
    EmptyTranscriptError,
    GeneratorFactory,
    stored_template,
    stored_vocabulary,
)
from vozata.ports import Localizer, SessionRepository
from vozata.session_title import stored_title

# Held around every read-modify-write of a meeting's partial minutes (writing, deleting).
_lock = threading.Lock()


def segments_in_range(
    segments: Sequence[TranscriptSegment], start: float, end: float | None
) -> list[TranscriptSegment]:
    """The segments that start in `[start, end)`; `end` None is up to the last one."""
    return [
        segment
        for segment in segments
        if segment.start >= start and (end is None or segment.start < end)
    ]


def write_partial_minutes(
    store: SessionRepository,
    session_id: str,
    build_generator: GeneratorFactory,
    labeler: SpeakerLabeler,
    localizer: Localizer,
    *,
    start: float,
    end: float | None,
    origin: str,
    live: bool,
    template: str | None = None,
    new_id: Callable[[], str] = lambda: uuid.uuid4().hex[:12],
    now: Callable[[], datetime] | None = None,
) -> PartialMinutes:
    """Minutes of the segments in `[start, end)` of the best transcript (while recording, the
    segments stored so far), added to the meeting's partial minutes and returned.

    Language, glossary, title, speaker names and template come from the metadata as for the final
    minutes. The prompt says which part this is: up to now (`live`), or the range. Raises
    `SessionNotFoundError`, `EmptyTranscriptError` (nothing said in the range) or
    `LanguageModelError`; on failure nothing is written.
    """
    meta = store.read_meta(session_id)
    segments = segments_in_range(store.load_transcript(session_id), start, end)
    if not segments:
        raise EmptyTranscriptError(session_id)
    covered_end = end if end is not None else max(segment.end for segment in segments)
    if live:
        scope = localizer.t("minutes.scope_live", end=format_timestamp(covered_end))
    else:
        scope = localizer.t(
            "minutes.scope_range", start=format_timestamp(start), end=format_timestamp(covered_end)
        )
    language = ConversationLanguage(meta.get("language", ConversationLanguage.AUTO.value))
    generator = build_generator(template or stored_template(meta))
    markdown = generator.generate(
        segments,
        labeler.with_names(store.speaker_names(session_id)),
        language,
        stored_vocabulary(meta),
        title=stored_title(meta),
        scope=scope,
    )
    written = (now or store.now)().isoformat(timespec="seconds")
    item = PartialMinutes(
        id=new_id(),
        created_at=written,
        start=start,
        end=round(covered_end, 3),
        origin=origin,
        markdown=markdown + "\n",
        template=generator.template_id,
    )
    with _lock:
        store.write_partial_minutes(session_id, [*store.read_partial_minutes(session_id), item])
    return item


def delete_partial_minutes(store: SessionRepository, session_id: str, partial_id: str) -> bool:
    """Remove one; False when the meeting has none with that id."""
    with _lock:
        items = store.read_partial_minutes(session_id)
        kept = [item for item in items if item.id != partial_id]
        if len(kept) == len(items):
            return False
        store.write_partial_minutes(session_id, kept)
        return True
