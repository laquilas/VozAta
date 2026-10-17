"""The transcript context for a question, never longer than `LLM_MAX_CHARS` (phase 24).

One session: the whole transcript when it fits, else the search hits with their neighbouring
segments. All sessions: the search hits, best first, grouped per session. Search terms are the
question's words minus the app language's stopwords (`qa.stopwords`); each term is searched on
its own (the index ANDs words), and segments matching more terms rank higher.
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime

from vozata.domain import TranscriptSegment
from vozata.formatting import render_line
from vozata.labels import SpeakerLabeler
from vozata.ports import Localizer, SessionNotFoundError, SessionRepository, TranscriptSearch

NEIGHBOURS = 2  # segments kept on each side of a hit (single session)
SEARCH_LIMIT = 200  # hits read per search term
_WORD = re.compile(r"\w+")


@dataclass(frozen=True)
class RetrievedContext:
    """The rendered context and, per session, the segments it shows (citations map to them)."""

    text: str = ""
    sessions: Mapping[str, tuple[TranscriptSegment, ...]] = field(default_factory=dict)

    @property
    def empty(self) -> bool:
        return not self.sessions


def keywords(question: str, stopwords: set[str]) -> list[str]:
    """Distinct words of `question` (case-folded, in order) that are not stopwords."""
    words: list[str] = []
    for word in _WORD.findall(question.casefold()):
        if len(word) > 1 and word not in stopwords and word not in words:
            words.append(word)
    return words


def session_date(session_id: str) -> str:
    """`20261015_202358` as `2026-10-15 20:23` (other ids unchanged)."""
    try:
        return datetime.strptime(session_id[:15], "%Y%m%d_%H%M%S").strftime("%Y-%m-%d %H:%M")
    except ValueError:
        return session_id


class Retriever:
    def __init__(
        self,
        store: SessionRepository,
        search: TranscriptSearch | None,
        labeler: SpeakerLabeler,
        localizer: Localizer,
        max_chars: int,
    ) -> None:
        self._store = store
        self._search = search
        self._labeler = labeler
        self._t = localizer.t
        self._max_chars = max_chars
        self._stopwords = set(localizer.t("qa.stopwords").casefold().split())

    def retrieve(self, question: str, session_id: str | None = None) -> RetrievedContext:
        """Raises `SessionNotFoundError` for an unknown `session_id`."""
        if session_id is not None:
            return self._one_session(question, session_id)
        return self._all_sessions(question)

    def _one_session(self, question: str, session_id: str) -> RetrievedContext:
        segments = sorted(self._store.load_transcript(session_id), key=lambda s: s.start)
        lines = self._lines(session_id, segments)
        budget = _Budget(self._max_chars)
        if budget.take(self._header(session_id), *lines):
            return _context([(self._header(session_id), session_id, segments, lines)])
        index = {segment.segment_id: n for n, segment in enumerate(segments)}
        budget = _Budget(self._max_chars - len(self._header(session_id)) - 1)
        chosen: set[int] = set()
        for hit_session, segment_id in self._ranked_hits(question):
            if hit_session != session_id or segment_id not in index:
                continue
            hit = index[segment_id]
            window = range(max(0, hit - NEIGHBOURS), min(len(segments), hit + NEIGHBOURS + 1))
            new = [n for n in window if n not in chosen]
            if new and budget.take(*(lines[n] for n in new)):
                chosen.update(new)
            elif hit not in chosen and budget.take(lines[hit]):
                chosen.add(hit)  # no room for the neighbours: the hit alone
        if not chosen:
            return RetrievedContext()
        kept = sorted(chosen)
        return _context(
            [
                (
                    self._header(session_id),
                    session_id,
                    [segments[n] for n in kept],
                    [lines[n] for n in kept],
                )
            ]
        )

    def _all_sessions(self, question: str) -> RetrievedContext:
        budget = _Budget(self._max_chars)
        picked: dict[str, list[TranscriptSegment]] = {}
        transcripts: dict[str, dict[str, TranscriptSegment] | None] = {}
        for session_id, segment_id in self._ranked_hits(question):
            if session_id not in transcripts:
                transcripts[session_id] = self._transcript(session_id)
            segment = (transcripts[session_id] or {}).get(segment_id)
            if segment is None:
                continue  # the session was deleted or re-transcribed since it was indexed
            line = self._lines(session_id, [segment])[0]
            if session_id in picked:
                if budget.take(line):
                    picked[session_id].append(segment)
            elif budget.take(self._header(session_id) + "\n", line):  # + the blank line
                picked[session_id] = [segment]
        blocks = []
        for session_id, segments in picked.items():
            ordered = sorted(segments, key=lambda s: s.start)
            lines = self._lines(session_id, ordered)
            blocks.append((self._header(session_id), session_id, ordered, lines))
        return _context(blocks)

    def _ranked_hits(self, question: str) -> list[tuple[str, str]]:
        """`(session_id, segment_id)` matching most terms first, then by best search rank."""
        if self._search is None:
            return []
        scores: dict[tuple[str, str], tuple[int, int]] = {}
        for term in keywords(question, self._stopwords):
            for rank, hit in enumerate(self._search.search(term, SEARCH_LIMIT)):
                key = (hit.session_id, hit.segment_id)
                matches, best = scores.get(key, (0, rank))
                scores[key] = (matches + 1, min(best, rank))
        return sorted(scores, key=lambda key: (-scores[key][0], scores[key][1]))

    def _transcript(self, session_id: str) -> dict[str, TranscriptSegment] | None:
        try:
            return {s.segment_id: s for s in self._store.load_transcript(session_id)}
        except SessionNotFoundError:
            return None

    def _lines(self, session_id: str, segments: Sequence[TranscriptSegment]) -> list[str]:
        labeler = self._labeler.with_names(self._store.speaker_names(session_id))
        return [render_line(segment, labeler.label(segment.speaker_id)) for segment in segments]

    def _header(self, session_id: str) -> str:
        return self._t("qa.session_header", id=session_id, date=session_date(session_id))


class _Budget:
    """Characters left for context; each line costs its length plus a newline (an upper bound)."""

    def __init__(self, max_chars: int) -> None:
        self.left = max_chars

    def take(self, *lines: str) -> bool:
        cost = sum(len(line) + 1 for line in lines)
        if cost > self.left:
            return False
        self.left -= cost
        return True


def _context(
    blocks: Sequence[tuple[str, str, Sequence[TranscriptSegment], Sequence[str]]],
) -> RetrievedContext:
    if not any(segments for _, _, segments, _ in blocks):
        return RetrievedContext()
    text = "\n\n".join("\n".join([header, *lines]) for header, _, _, lines in blocks)
    sessions = {session_id: tuple(segments) for _, session_id, segments, _ in blocks}
    return RetrievedContext(text, sessions)
