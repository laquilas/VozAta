from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from vozata.ports import TranslationError, Translator
from vozata.translation import opus_mt
from vozata.translation.opus_mt import (
    CTranslate2Marian,
    OpusMtTranslator,
    Step,
    folder_locator,
    hub_locator,
    route,
)


@pytest.mark.parametrize(
    ("source", "target", "steps"),
    [
        ("en", "en", []),
        ("en", "pt", [Step("en-ROMANCE", ">>pt_br<<")]),
        ("en", "es", [Step("en-ROMANCE", ">>es<<")]),
        ("pt", "en", [Step("ROMANCE-en")]),
        ("es", "en", [Step("ROMANCE-en")]),
        ("pt", "es", [Step("ROMANCE-en"), Step("en-ROMANCE", ">>es<<")]),
        ("es", "pt", [Step("ROMANCE-en"), Step("en-ROMANCE", ">>pt_br<<")]),
    ],
)
def test_route_covers_every_pair(source: str, target: str, steps: list[Step]) -> None:
    assert route(source, target) == steps


def test_route_rejects_unsupported_languages() -> None:
    with pytest.raises(TranslationError, match="de -> en"):
        route("de", "en")


class FakeModel:
    def __init__(self, name: str) -> None:
        self.name = name

    def translate(self, text: str, prefix: str | None) -> str:
        return f"{self.name}{prefix or ''}({text})"


def test_translator_chains_models_and_loads_each_once() -> None:
    loads: list[Path] = []

    def load(folder: Path) -> FakeModel:
        loads.append(folder)
        return FakeModel(folder.name)

    translator = OpusMtTranslator(lambda name: Path(name), load)
    assert isinstance(translator, Translator)

    assert translator.translate("olá", "pt", "es") == "en-ROMANCE>>es<<(ROMANCE-en(olá))"
    assert translator.translate("hola", "es", "en") == "ROMANCE-en(hola)"
    assert translator.translate("same", "en", "en") == "same"
    assert loads == [Path("ROMANCE-en"), Path("en-ROMANCE")]

    translator.close()
    translator.translate("again", "es", "en")
    assert len(loads) == 3  # reloaded after close


def test_folder_locator_finds_converted_models(tmp_path: Path) -> None:
    folder = tmp_path / "opus-mt-en-ROMANCE"
    folder.mkdir()
    (folder / "model.bin").write_bytes(b"x")
    locate = folder_locator(tmp_path)

    assert locate("en-ROMANCE") == folder
    with pytest.raises(TranslationError, match="ct2fast-opus-mt-ROMANCE-en"):
        locate("ROMANCE-en")


def test_hub_locator_downloads_the_registered_repo(tmp_path: Path) -> None:
    repos: list[str] = []

    def download(repo: str) -> str:
        repos.append(repo)
        return str(tmp_path)

    assert hub_locator(download)("ROMANCE-en") == tmp_path
    assert repos == ["michaelfeil/ct2fast-opus-mt-ROMANCE-en"]


def test_hub_locator_wraps_download_failures() -> None:
    def download(repo: str) -> str:
        raise OSError("offline")

    with pytest.raises(TranslationError, match="offline"):
        hub_locator(download)("en-ROMANCE")


class FakePieces:
    def encode(self, text: str, out_type: type) -> list[str]:
        return ["▁" + word for word in text.split()]

    def decode(self, pieces: list[str]) -> str:
        return " " + "".join(pieces).replace("▁", " ").strip() + " "


class FakeCt2:
    def __init__(self, error: Exception | None = None) -> None:
        self.error = error
        self.batches: list[list[list[str]]] = []

    def translate_batch(self, batch: list[list[str]], beam_size: int) -> list[SimpleNamespace]:
        self.batches.append(batch)
        if self.error is not None:
            raise self.error
        return [SimpleNamespace(hypotheses=[["▁bom", "▁dia"]])]


def test_ctranslate2_marian_adds_the_target_token_and_eos() -> None:
    ct2 = FakeCt2()
    model = CTranslate2Marian(ct2, FakePieces(), FakePieces())

    assert model.translate("good morning", ">>pt_br<<") == "bom dia"
    assert ct2.batches == [[[">>pt_br<<", "▁good", "▁morning", "</s>"]]]
    model.translate("hi", None)
    assert ct2.batches[1] == [["▁hi", "</s>"]]


def test_ctranslate2_marian_wraps_model_errors() -> None:
    model = CTranslate2Marian(FakeCt2(RuntimeError("bad input")), FakePieces(), FakePieces())

    with pytest.raises(TranslationError, match="bad input"):
        model.translate("hi", None)


def test_from_settings_fails_fast_without_the_extra(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(opus_mt.importlib.util, "find_spec", lambda name: None)

    with pytest.raises(TranslationError, match="translation"):
        opus_mt.from_settings(None)


def test_from_settings_picks_the_locator(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr(opus_mt.importlib.util, "find_spec", lambda name: object())

    assert isinstance(opus_mt.from_settings(tmp_path), OpusMtTranslator)
    assert isinstance(opus_mt.from_settings(None), OpusMtTranslator)
