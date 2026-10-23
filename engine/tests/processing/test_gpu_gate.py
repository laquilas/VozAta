import logging
import threading

import pytest

from vozata.config import Settings
from vozata.domain import WhisperDevice
from vozata.processing.cancel import CancelToken, StepCancelled
from vozata.processing.gpu_gate import GpuGate, GpuUsage, GpuUser, gpu_usage

TIMEOUT = 2.0


def test_priority_cancels_running_queue_step_and_waits_for_it():
    gate = GpuGate()
    token = CancelToken()
    in_step = threading.Event()
    release = threading.Event()
    order: list[str] = []

    def queue() -> None:
        with gate.queue_step(token, lambda: None):
            in_step.set()
            release.wait(TIMEOUT)
            order.append("step-exit")

    thread = threading.Thread(target=queue)
    thread.start()
    assert in_step.wait(TIMEOUT)
    token.on_cancel(release.set)

    with gate.priority(GpuUser.LIVE):
        order.append("priority-enter")
        assert token.cancelled is True
        assert gate.priority_held is True
    thread.join(TIMEOUT)
    assert order == ["step-exit", "priority-enter"]
    assert gate.priority_held is False


def test_queue_step_waits_while_priority_held_and_calls_on_wait_once():
    gate = GpuGate()
    waits: list[int] = []
    entered = threading.Event()
    waiting = threading.Event()

    def on_wait() -> None:
        waits.append(1)
        waiting.set()

    def queue() -> None:
        with gate.queue_step(CancelToken(), on_wait):
            entered.set()

    with gate.priority(GpuUser.ASK):
        thread = threading.Thread(target=queue)
        thread.start()
        assert waiting.wait(TIMEOUT)
        assert entered.wait(0.1) is False
    assert entered.wait(TIMEOUT)
    thread.join(TIMEOUT)
    assert waits == [1]


def test_queue_step_does_not_call_on_wait_when_free():
    gate = GpuGate()
    waits: list[int] = []
    with gate.queue_step(CancelToken(), lambda: waits.append(1)):
        pass
    assert waits == []


def test_queue_step_raises_when_token_already_cancelled():
    gate = GpuGate()
    token = CancelToken()
    token.cancel()
    with pytest.raises(StepCancelled), gate.queue_step(token, lambda: None):
        pytest.fail("must not enter")


def test_queue_step_raises_when_cancelled_while_waiting():
    gate = GpuGate()
    token = CancelToken()
    waiting = threading.Event()
    result: list[type] = []

    def queue() -> None:
        try:
            with gate.queue_step(token, waiting.set):
                result.append(type(None))
        except StepCancelled:
            result.append(StepCancelled)

    with gate.priority(GpuUser.CHECK):
        thread = threading.Thread(target=queue)
        thread.start()
        assert waiting.wait(TIMEOUT)
        token.cancel()
    thread.join(TIMEOUT)
    assert result == [StepCancelled]


def test_two_priority_users_hold_together():
    gate = GpuGate()
    with gate.priority(GpuUser.LIVE):
        with gate.priority(GpuUser.ASK):
            assert gate.priority_held is True
        assert gate.priority_held is True
    assert gate.priority_held is False


def test_priority_proceeds_after_cancel_timeout_when_step_ignores_cancel(caplog):
    gate = GpuGate(cancel_timeout=0.05)
    token = CancelToken()
    in_step = threading.Event()
    release = threading.Event()

    def queue() -> None:
        with gate.queue_step(token, lambda: None):
            in_step.set()
            release.wait(TIMEOUT)

    thread = threading.Thread(target=queue)
    thread.start()
    assert in_step.wait(TIMEOUT)
    with caplog.at_level(logging.WARNING), gate.priority(GpuUser.LIVE):
        assert token.cancelled is True
    assert any(r.levelno == logging.WARNING for r in caplog.records)
    release.set()
    thread.join(TIMEOUT)


def test_priority_without_running_step_does_not_wait():
    gate = GpuGate(cancel_timeout=5.0)
    with gate.priority(GpuUser.QUEUE):
        assert gate.priority_held is True


def _settings(**overrides) -> Settings:
    return Settings(**overrides)  # type: ignore[arg-type]


@pytest.mark.parametrize(
    ("provider", "device", "cuda", "expected"),
    [
        ("faster_whisper", WhisperDevice.AUTO, True, True),
        ("faster_whisper", WhisperDevice.AUTO, False, False),
        ("faster_whisper", WhisperDevice.CUDA, True, True),
        ("faster_whisper", WhisperDevice.CPU, True, False),
        ("other", WhisperDevice.AUTO, True, False),
    ],
)
def test_gpu_usage_speech(provider, device, cuda, expected):
    settings = _settings(stt_provider=provider, whisper_device=device)
    assert gpu_usage(settings, cuda=cuda).speech is expected


@pytest.mark.parametrize(
    ("provider", "device", "cuda", "fallback"),
    [
        ("vozata_worker", WhisperDevice.AUTO, True, True),
        ("vozata_worker", WhisperDevice.CPU, True, False),
        ("vozata_worker", WhisperDevice.AUTO, False, False),
        ("faster_whisper", WhisperDevice.AUTO, True, False),
    ],
)
def test_speech_on_the_worker_is_not_local_gpu_work_but_its_fallback_is(
    provider, device, cuda, fallback
):
    usage = gpu_usage(_settings(stt_provider=provider, whisper_device=device), cuda=cuda)

    assert usage.speech_fallback is fallback
    assert usage.speech is (provider == "faster_whisper")


@pytest.mark.parametrize(
    ("diarization", "live", "device", "cuda", "expected"),
    [
        (True, False, WhisperDevice.AUTO, True, True),
        (False, True, WhisperDevice.AUTO, True, True),
        (False, False, WhisperDevice.AUTO, True, False),
        (True, False, WhisperDevice.CPU, True, False),
        (True, False, WhisperDevice.AUTO, False, False),
    ],
)
def test_gpu_usage_speakers(diarization, live, device, cuda, expected):
    settings = _settings(
        diarization_enabled=diarization,
        live_diarization_enabled=live,
        diarization_device=device,
    )
    assert gpu_usage(settings, cuda=cuda).speakers is expected


@pytest.mark.parametrize(
    ("diarization", "live", "device", "cuda", "expected"),
    [
        (True, False, WhisperDevice.AUTO, True, False),  # post-session pyannote only
        (False, True, WhisperDevice.AUTO, True, True),
        (True, True, WhisperDevice.CPU, True, False),
        (False, True, WhisperDevice.AUTO, False, False),
    ],
)
def test_gpu_usage_live_speakers(diarization, live, device, cuda, expected):
    settings = _settings(
        diarization_enabled=diarization,
        live_diarization_enabled=live,
        diarization_device=device,
    )
    assert gpu_usage(settings, cuda=cuda).live_speakers is expected


@pytest.mark.parametrize(
    ("provider", "cuda", "expected"),
    [("ollama", True, True), ("ollama", False, False), ("other", True, False)],
)
def test_gpu_usage_llm(provider, cuda, expected):
    assert gpu_usage(_settings(llm_provider=provider), cuda=cuda).llm is expected


@pytest.mark.parametrize(
    ("url", "expected"),
    [
        ("http://localhost:11434", True),
        ("http://127.0.0.1:11434", True),
        ("http://192.168.0.20:11434", False),
        ("gpu-box:11434", False),
    ],
)
def test_gpu_usage_remote_ollama_is_not_local_gpu_work(url, expected):
    settings = _settings(llm_provider="ollama", ollama_url=url)

    assert gpu_usage(settings, cuda=True).llm is expected


def test_gpu_usage_remote_ollama_leaves_the_speech_model_on_the_gpu():
    settings = _settings(llm_provider="ollama", ollama_url="http://192.168.0.20:11434")

    usage = gpu_usage(settings, cuda=True)

    assert usage.speech is True and usage.llm is False


def test_gpu_usage_is_a_frozen_value():
    assert GpuUsage(speech=True, speakers=False, llm=False) == GpuUsage(True, False, False)


@pytest.mark.parametrize(
    ("provider", "device", "cuda", "local", "fallback"),
    [
        ("pyannote", WhisperDevice.AUTO, True, True, False),
        ("vozata_worker", WhisperDevice.AUTO, True, False, True),
        ("vozata_worker", WhisperDevice.CPU, True, False, False),
        ("vozata_worker", WhisperDevice.AUTO, False, False, False),
    ],
)
def test_speakers_on_the_worker_are_not_local_gpu_work_but_their_fallback_is(
    provider, device, cuda, local, fallback
):
    settings = _settings(
        diarization_provider=provider,
        diarization_device=device,
        diarization_enabled=True,
        live_diarization_enabled=True,
    )

    usage = gpu_usage(settings, cuda=cuda)

    assert (usage.speakers, usage.live_speakers, usage.speakers_fallback) == (
        local,
        local,
        fallback,
    )


@pytest.mark.parametrize(
    ("values", "expected"),
    [
        # phase 53: LM Studio / llama.cpp on this PC use its GPU like Ollama
        ({"llm_provider": "openai_compatible", "openai_llm_url": "http://localhost:1234/v1"}, True),
        (
            {"llm_provider": "openai_compatible", "openai_llm_url": "http://192.168.0.9:1234/v1"},
            False,
        ),
        ({"llm_provider": "anthropic"}, False),
    ],
)
def test_gpu_usage_llm_of_the_other_providers(values, expected):
    assert gpu_usage(_settings(**values), cuda=True).llm is expected
