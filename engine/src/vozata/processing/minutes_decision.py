"""Whether a meeting's minutes are written when it is processed (phase 64).

Back-to-back meetings must never wait for minutes. They are skipped, and the meeting is marked
`minutes_skipped` so the app shows "minutes not generated" with a button for later, when:

- `not_ready`: the engine was not following the recording when it stopped (it was down or still
  starting; the recording was replayed later), or the language model does not answer now;
- `by_user`: the meeting's own "generate minutes when finished" option is off.

`GENERATE_MINUTES=false` turns minutes off for every meeting: nothing is marked.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Any

NOT_READY = "not_ready"
BY_USER = "by_user"


def minutes_skip_reason(
    generate_setting: bool, meta: Mapping[str, Any], model_ready: Callable[[], bool]
) -> str | None:
    """None when the minutes are written; else why they are not (None too when off globally)."""
    if not generate_setting:
        return None
    if meta.get("minutes_not_ready"):
        return NOT_READY
    if meta.get("generate_minutes") is False:
        return BY_USER
    if not model_ready():
        return NOT_READY
    return None
