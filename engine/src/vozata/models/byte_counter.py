"""tqdm-compatible byte counter for huggingface_hub's `snapshot_download(tqdm_class=...)`.

huggingface_hub 2.2.0 creates two byte bars (`unit="B"`): "transfer" (network bytes) and
"reconstruct" (bytes written to disk). Over plain HTTP both get every chunk, so summing them would
count each byte twice; the counter reports the furthest of the byte bars instead. The per-file
count bar `hf_thread_map` creates (no unit) is ignored.
"""

from __future__ import annotations

import threading
from typing import Any

from vozata.models.tracker import DownloadHandle


def byte_counter(handle: DownloadHandle) -> type:
    """A tqdm-compatible class that forwards the downloaded bytes to `handle`."""
    lock = threading.Lock()
    byte_bars: list[_Bar] = []
    reported = [0]

    class _Bar:
        def __init__(
            self, *args: Any, total: Any = None, initial: Any = 0, unit: str = "it", **kwargs: Any
        ) -> None:
            self.total = total
            self.unit = unit
            self.n = 0
            self.format_dict: dict[str, Any] = {}
            if unit == "B":
                with lock:
                    byte_bars.append(self)
            self.update(initial)

        def update(self, n: float | None = 1) -> None:
            if not n:
                return
            with lock:
                self.n += int(n)
                if self.unit != "B":
                    return
                gain = max(bar.n for bar in byte_bars) - reported[0]
                if gain <= 0:
                    return
                reported[0] += gain
            handle.advance(gain)

        def __enter__(self) -> _Bar:
            return self

        def __exit__(self, *exc: object) -> None:
            self.close()

        def close(self) -> None:
            pass

        def refresh(self, *args: Any, **kwargs: Any) -> None:
            pass

        def set_description(self, *args: Any, **kwargs: Any) -> None:
            pass

        def set_description_str(self, *args: Any, **kwargs: Any) -> None:
            pass

        def set_postfix_str(self, *args: Any, **kwargs: Any) -> None:
            pass

    return _Bar
