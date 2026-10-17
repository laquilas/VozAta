"""Opus-MT (MarianMT) translation with CTranslate2 on CPU (phase 29, optional extra `translation`).

Two models cover every pair of `en`, `pt` and `es`: `ROMANCE-en` translates Portuguese and Spanish
into English, `en-ROMANCE` translates English into either (a `>>xx<<` token picks the language).
`pt` <-> `es` pivots through English. The models are Apache-2.0 / CC-BY 4.0 Opus-MT checkpoints
already converted to CTranslate2 (~155 MB each). `ctranslate2` ships with faster-whisper;
`sentencepiece` (the extra) and `huggingface_hub` are imported only when a model loads, so the
engine works without them. Models run on CPU with int8 weights (VRAM rule: Whisper owns the GPU).
"""

from __future__ import annotations

import importlib.util
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

from vozata.ports import TranslationError

MODELS = {
    "ROMANCE-en": "michaelfeil/ct2fast-opus-mt-ROMANCE-en",
    "en-ROMANCE": "michaelfeil/ct2fast-opus-mt-en-ROMANCE",
}
TARGET_TOKENS = {"pt": ">>pt_br<<", "es": ">>es<<"}  # en-ROMANCE target-language tokens
LANGUAGES = ("en", "pt", "es")
CPU_THREADS = 2  # leave the other cores to capture, VAD and the API
BEAM_SIZE = 2
MISSING_EXTRA = (
    "the optional extra 'translation' is not installed "
    '(run: python -m pip install -e ".[translation]" in engine/)'
)


@dataclass(frozen=True)
class Step:
    """One model pass: the model name (`MODELS` key) and its target token, if any."""

    model: str
    prefix: str | None = None


def route(source: str, target: str) -> list[Step]:
    """The model passes from `source` to `target` (none when they are equal)."""
    if source not in LANGUAGES or target not in LANGUAGES:
        raise TranslationError(f"unsupported language pair {source} -> {target}")
    if source == target:
        return []
    steps = [] if source == "en" else [Step("ROMANCE-en")]
    if target != "en":
        steps.append(Step("en-ROMANCE", TARGET_TOKENS[target]))
    return steps


class MarianModel(Protocol):
    def translate(self, text: str, prefix: str | None) -> str: ...


ModelLocator = Callable[[str], Path]  # model name -> folder with model.bin and the .spm files
ModelLoader = Callable[[Path], MarianModel]


class OpusMtTranslator:
    """The `Translator` port over Opus-MT models, each loaded once on first use."""

    def __init__(self, locate: ModelLocator, load: ModelLoader) -> None:
        self._locate = locate
        self._load = load
        self._models: dict[str, MarianModel] = {}

    def translate(self, text: str, source: str, target: str) -> str:
        for step in route(source, target):
            text = self._model(step.model).translate(text, step.prefix)
        return text

    def close(self) -> None:
        self._models.clear()  # CTranslate2 frees the weights with the last reference

    def _model(self, name: str) -> MarianModel:
        if name not in self._models:
            self._models[name] = self._load(self._locate(name))
        return self._models[name]


def folder_locator(root: Path) -> ModelLocator:
    """Models already on disk: `<root>/opus-mt-<name>` (`TRANSLATION_MODEL_DIR`)."""

    def locate(name: str) -> Path:
        folder = root / f"opus-mt-{name}"
        if not (folder / "model.bin").is_file():
            raise TranslationError(f"model {MODELS[name]} not found in {folder}")
        return folder

    return locate


def hub_locator(download: Callable[[str], str] | None = None) -> ModelLocator:
    """Models from Hugging Face, downloaded once into its cache (`TRANSLATION_MODEL_DIR` empty)."""

    def locate(name: str) -> Path:
        fetch = download or _snapshot_download
        try:
            return Path(fetch(MODELS[name]))
        except Exception as error:
            raise TranslationError(f"downloading {MODELS[name]} failed: {error}") from error

    return locate


def _snapshot_download(repo: str) -> str:  # pragma: no cover - network
    from huggingface_hub import snapshot_download

    return snapshot_download(repo)


class CTranslate2Marian:
    """One Opus-MT model: SentencePiece pieces in, CTranslate2 greedy-ish beam, pieces out."""

    def __init__(self, translator: Any, source: Any, target: Any) -> None:
        self._translator = translator
        self._source = source
        self._target = target

    def translate(self, text: str, prefix: str | None) -> str:
        pieces = self._source.encode(text, out_type=str)
        tokens = ([prefix] if prefix else []) + pieces + ["</s>"]
        try:
            results = self._translator.translate_batch([tokens], beam_size=BEAM_SIZE)
        except Exception as error:
            raise TranslationError(f"translation failed: {error}") from error
        return self._target.decode(results[0].hypotheses[0]).strip()


def require_extra() -> None:
    """Fail fast (before any download) when `sentencepiece` is missing."""
    if importlib.util.find_spec("sentencepiece") is None:
        raise TranslationError(MISSING_EXTRA)


def load_ctranslate2(folder: Path) -> MarianModel:  # pragma: no cover - needs the extra and a model
    try:
        import ctranslate2
        import sentencepiece
    except ImportError as error:
        raise TranslationError(MISSING_EXTRA) from error
    try:
        translator = ctranslate2.Translator(
            str(folder), device="cpu", compute_type="int8", intra_threads=CPU_THREADS
        )
        source = sentencepiece.SentencePieceProcessor(model_file=str(folder / "source.spm"))
        target = sentencepiece.SentencePieceProcessor(model_file=str(folder / "target.spm"))
    except Exception as error:
        raise TranslationError(f"loading the model in {folder} failed: {error}") from error
    return CTranslate2Marian(translator, source, target)


def from_settings(model_dir: Path | None) -> OpusMtTranslator:
    """The configured provider: `TRANSLATION_MODEL_DIR` folders, else the Hugging Face cache."""
    require_extra()
    locate = folder_locator(model_dir) if model_dir is not None else hub_locator()
    return OpusMtTranslator(locate, load_ctranslate2)
