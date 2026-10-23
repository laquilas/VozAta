"""Live translation on the VozAta worker, with a switch to this PC (phase 46)."""

from __future__ import annotations

from collections.abc import Callable

from vozata.ports import FallbackNotices, TranslationError, Translator, WorkerUnreachableError
from vozata.worker_client.client import WorkerClient, WorkerRequestError


class WorkerTranslator:
    """`Translator`: one request per committed segment; a worker that does not answer is replaced
    by the local translator, once, with a notice."""

    def __init__(
        self,
        client: WorkerClient,
        local_factory: Callable[[], Translator],
        notices: FallbackNotices,
    ) -> None:
        self._client = client
        self._local_factory = local_factory
        self._notices = notices
        self._local: Translator | None = None

    def translate(self, text: str, source: str, target: str) -> str:
        if self._local is None:
            try:
                return self._client.translate(text, source, target)
            except WorkerUnreachableError as error:
                self._notices.fallback("translation", error.host)
                self._local = self._local_factory()
            except WorkerRequestError as error:
                raise TranslationError(str(error)) from error
        return self._local.translate(text, source, target)

    def close(self) -> None:
        self._client.close()
        if self._local is not None:
            self._local.close()
