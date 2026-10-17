"""Display labels for speaker ids (resolved at render time, never stored in raw data)."""

from __future__ import annotations

import re
from collections.abc import Mapping

from vozata.domain import Channel
from vozata.ports import Localizer

_DIARIZED = re.compile(r"^system:([1-9][0-9]*)$")


class SpeakerLabeler:
    """Label `mic`, `system` and diarized `system:<n>` speakers.

    Precedence: a user-given name, then the configured override, then the localized default.
    """

    def __init__(
        self,
        localizer: Localizer,
        mic_override: str | None = None,
        system_override: str | None = None,
        names: Mapping[str, str] | None = None,
    ) -> None:
        self._localizer = localizer
        self._mic_override = mic_override
        self._system_override = system_override
        self._overrides = {Channel.MIC.value: mic_override, Channel.SYSTEM.value: system_override}
        self._names = {key: name.strip() for key, name in (names or {}).items() if name.strip()}

    def with_names(self, names: Mapping[str, str]) -> SpeakerLabeler:
        """A labeler for one session: same overrides, plus the names from its `speakers.json`."""
        if not names:
            return self
        return SpeakerLabeler(self._localizer, self._mic_override, self._system_override, names)

    def label(self, speaker_id: str) -> str:
        if speaker_id in self._names:
            self._default(speaker_id)  # validates the id
            return self._names[speaker_id]
        return self._default(speaker_id)

    def _default(self, speaker_id: str) -> str:
        if speaker_id in self._overrides:
            return self._overrides[speaker_id] or self._localizer.t(f"labels.{speaker_id}")
        match = _DIARIZED.match(speaker_id)
        if match is None:
            raise ValueError(f"Unknown speaker id {speaker_id!r}")
        return self._localizer.t("labels.user", n=int(match.group(1)))
