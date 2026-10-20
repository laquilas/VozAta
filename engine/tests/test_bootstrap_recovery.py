"""Composition of crash recovery (phase 17)."""

from __future__ import annotations

from pathlib import Path

import pytest

from tests.fakes import FakeLanguageModel, FakeSessionObserver
from tests.test_session_recover import make_session_folder
from vozata import bootstrap
from vozata.audio.mixer import MonoMixer, StereoMixer
from vozata.config import Settings
from vozata.domain import ConversationLanguage, MixMode, StorageBackend
from vozata.minutes.action_items import ActionItemExtractor
from vozata.processing.cancel import CancelToken
from vozata.storage.files.audio import FileAudioStore
from vozata.storage.files.repository import FileSessionRepository
from vozata.storage.search_index import SearchIndex


def _settings(tmp_path: Path, **overrides: object) -> Settings:
    """The file backend: these tests build crashed session folders (phase 17)."""
    overrides.setdefault("storage_backend", StorageBackend.FILES)
    return Settings(output_dir=tmp_path / "recordings", **overrides)  # type: ignore[arg-type]


def test_the_recovery_session_takes_template_glossary_and_mix_mode_from_session_json(
    tmp_path: Path,
) -> None:
    settings = _settings(tmp_path, mix_mode=MixMode.MONO)
    store = bootstrap.build_store(settings)
    session_id = make_session_folder(
        store,
        template="daily",
        vocabulary=["Avalonia", "N5"],
        settings={"MIX_MODE": "stereo"},
    )

    audio = bootstrap.build_audio_store(settings)
    session = bootstrap.build_recovery_session(
        settings, store, audio, FakeSessionObserver(), session_id
    )

    components = session._c
    assert components.minutes is not None
    assert components.minutes.template_id == "daily"
    assert components.minutes_template == "daily"
    assert components.vocabulary == ("Avalonia", "N5")
    assert isinstance(components.mixer, StereoMixer)
    assert isinstance(components.search_index, SearchIndex)
    assert isinstance(components.action_items, ActionItemExtractor)
    assert components.diarizer_factory is None
    assert components.sources == {}
    assert components.clock.now() == 0.0
    components.clock.start()
    with pytest.raises(RuntimeError):
        components.transcriber_factory()


def test_defaults_apply_when_session_json_lacks_them(tmp_path: Path) -> None:
    settings = _settings(
        tmp_path,
        mix_mode=MixMode.STEREO,
        generate_minutes=False,
        diarization_enabled=True,
    )
    other = bootstrap.build_store(settings, tmp_path / "elsewhere")  # not OUTPUT_DIR: not indexed
    session_id = make_session_folder(other, template="gone", vocabulary="bad", settings=[])

    audio = bootstrap.build_audio_store(settings, tmp_path / "elsewhere")
    session = bootstrap.build_recovery_session(
        settings, other, audio, FakeSessionObserver(), session_id
    )

    components = session._c
    assert components.minutes is None
    assert components.action_items is None
    assert components.minutes_template == "general"
    assert components.vocabulary == ()
    assert isinstance(components.mixer, StereoMixer)
    assert components.search_index is None
    assert components.diarizer_factory is not None


def test_the_finisher_takes_its_components_language_and_title_from_session_json(
    tmp_path: Path,
) -> None:
    settings = _settings(tmp_path, mix_mode=MixMode.MONO)
    store = bootstrap.build_store(settings)
    session_id = make_session_folder(
        store, template="daily", vocabulary=["Avalonia"], settings={"MIX_MODE": "stereo"}
    )
    audio = bootstrap.build_audio_store(settings)

    finisher = bootstrap.build_finisher(settings, store, audio, FakeSessionObserver(), session_id)

    components = finisher._c
    assert components.minutes is not None and components.minutes.template_id == "daily"
    assert components.vocabulary == ("Avalonia",)
    assert isinstance(components.mixer, StereoMixer)
    assert isinstance(components.search_index, SearchIndex)
    assert finisher._lock.language is ConversationLanguage.PT
    assert finisher._title() is None
    store.write_meta(session_id, {**store.read_meta(session_id), "title": "Budget"})
    assert finisher._title() == "Budget"  # read when needed, not captured


def test_a_finisher_runs_the_steps_of_a_stored_session(tmp_path: Path) -> None:
    settings = _settings(tmp_path, generate_minutes=False)
    store = bootstrap.build_store(settings)
    audio = bootstrap.build_audio_store(settings)
    session_id = make_session_folder(store)
    observer = FakeSessionObserver()

    finisher = bootstrap.build_finisher(settings, store, audio, observer, session_id)
    token = CancelToken()
    finisher.mix()
    finisher.identify_speakers(token)
    finisher.write_minutes(token)
    finisher.extract_action_items(token)
    finisher.index()
    finisher.ended(store.now())

    assert observer.of("error") == []
    assert store.paths(session_id).mixed_wav.is_file()
    assert store.read_meta(session_id)["status"] == "done"


def test_action_items_follow_extract_action_items(tmp_path: Path) -> None:
    settings = _settings(tmp_path, extract_action_items=False)
    store = bootstrap.build_store(settings)
    session_id = make_session_folder(store)

    audio = bootstrap.build_audio_store(settings)
    session = bootstrap.build_recovery_session(
        settings, store, audio, FakeSessionObserver(), session_id
    )

    assert session._c.minutes is not None
    assert session._c.action_items is None


def test_build_recovery_finishes_a_session_with_the_current_settings(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    current = _settings(tmp_path, generate_minutes=False)  # e.g. saved through PUT /settings
    before: list[str] = []
    recovery = bootstrap.build_recovery(
        settings, current=lambda: current, before_finish=lambda: before.append("release")
    )
    session_id = make_session_folder(recovery.store, status="recording")

    assert recovery.find_interrupted() == [session_id]
    assert recovery.recover(session_id, FakeSessionObserver()) is True

    store = recovery.store
    assert before == ["release"]
    assert store.read_meta(session_id)["status"] == "done"
    assert store.paths(session_id).mixed_wav.is_file()
    assert not store.paths(session_id).minutes_md.exists()
    [hit] = SearchIndex(tmp_path / "recordings" / "index.db").search("hello")
    assert hit.session_id == session_id


@pytest.mark.parametrize("keep_loaded", [False, True])
def test_the_api_container_recovers_through_its_session_manager(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, keep_loaded: bool
) -> None:
    monkeypatch.setitem(bootstrap.LANGUAGE_MODELS, "fake", lambda settings: FakeLanguageModel())
    settings = _settings(
        tmp_path, llm_provider="fake", generate_minutes=False, whisper_keep_loaded=keep_loaded
    )
    container = bootstrap.build_api_container(settings, env_file=tmp_path / ".env")
    session_id = make_session_folder(container.store, status="finalizing")

    assert container.manager.interrupted_sessions() == [session_id]
    container.manager.recover(session_id)
    assert container.manager.wait_until_finished(5)

    assert container.store.read_meta(session_id)["status"] == "done"


def test_the_cli_waits_two_autosaves_and_some_slack_before_calling_a_session_interrupted(
    tmp_path: Path,
) -> None:
    assert bootstrap.cli_stale_after(Settings(autosave_seconds=10)) == 25
    recovery = bootstrap.build_recovery(_settings(tmp_path), stale_after=25)
    assert isinstance(recovery.store, FileSessionRepository)
    assert [type(repair) for repair in recovery._repairs] == [
        FileAudioStore,
        FileSessionRepository,
    ]
    assert isinstance(bootstrap.MIXERS[MixMode.MONO](), MonoMixer)
