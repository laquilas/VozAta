"""Listen for voice commands in the live transcript (phase 50)."""

from __future__ import annotations

import logging
import time
from collections.abc import Callable

from vozata.commands.matcher import CommandMatcher, words
from vozata.domain import Channel, TranscriptSegment, VoiceCommand

_log = logging.getLogger(__name__)

COOLDOWN_SECONDS = 15.0  # one action at most once per cooldown (a repeated or re-heard command)
FOLLOW_SECONDS = 5.0  # a wake word alone waits this long for the command in the next segment


class VoiceCommandSink:
    """A `TranscriptSink` of the live pipeline, after echo dedupe: only microphone segments count,
    so speech played by the speakers never runs a command. `emit` compares short texts and calls
    `on_command(command, at)`, which must return quickly (it starts a job); `at` is when the wake
    word was said (session seconds, phase 59). A command said again within the cooldown calls
    `on_repeat(command, at)` instead."""

    def __init__(
        self,
        matcher: CommandMatcher,
        on_command: Callable[[VoiceCommand, float], None],
        clock: Callable[[], float] = time.monotonic,
        cooldown: float = COOLDOWN_SECONDS,
        follow: float = FOLLOW_SECONDS,
        on_repeat: Callable[[VoiceCommand, float], None] = lambda command, at: None,
    ) -> None:
        self._matcher = matcher
        self._on_command = on_command
        self._on_repeat = on_repeat
        self._wake_at = 0.0  # when the lone wake word was said
        self._clock = clock
        self._cooldown = cooldown
        self._follow = follow
        self._waiting_until: float | None = None  # session time a lone wake word waits until
        self._last: dict[str, float] = {}

    def emit(self, segment: TranscriptSegment) -> None:
        if segment.channel is not Channel.MIC:
            return
        try:
            self._check(segment)
        except Exception:  # a command must never stop the transcript
            _log.exception("Checking a voice command failed")

    def close(self) -> None:
        pass

    def _check(self, segment: TranscriptSegment) -> None:
        waiting, self._waiting_until = self._waiting_until, None
        if waiting is not None and segment.start <= waiting:
            command = self._matcher.command(words(segment.text))
            if command is not None:
                self._fire(command, self._wake_at)
                return
        spoken = self._matcher.after_wake(segment.text)
        if spoken is None:
            return
        command = self._matcher.command(spoken) if spoken else None
        if command is not None:
            self._fire(command, segment.start)
        elif not spoken:  # "VozAta." and a pause: the command comes in the next segment
            self._waiting_until = segment.end + self._follow
            self._wake_at = segment.start

    def _fire(self, command: VoiceCommand, at: float) -> None:
        now = self._clock()
        last = self._last.get(command.action)
        if last is not None and now - last < self._cooldown:
            _log.info(
                "Voice command %r ignored: said again within %.0f s", command.phrase, self._cooldown
            )
            self._on_repeat(command, at)
            return
        self._last[command.action] = now
        _log.info("Voice command: %s (%s)", command.phrase, command.action)
        self._on_command(command, at)
