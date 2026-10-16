"""Manual smoke check for audio capture (phase 02).

Records the default microphone and the default loopback for a few seconds into a temporary
folder, then reports each WAV's duration and level. With --tone, plays a short quiet 440 Hz tone
on the default output so the loopback track has content.

Run from `engine/`:  ../.venv/Scripts/python scripts/smoke_capture.py --seconds 10 --tone
"""

from __future__ import annotations

import argparse
import tempfile
import threading
import time
import wave
from pathlib import Path

import numpy as np

from vozata.audio.capture import WasapiSource
from vozata.audio.clock import SessionClock
from vozata.audio.devices import default_input, default_loopback
from vozata.audio.levels import rms_db
from vozata.audio.wav_writer import AlignedWavWriter

RATE = 16000


def _play_tone(folder: Path, seconds: float = 3.0) -> None:
    import winsound

    t = np.arange(int(44100 * seconds)) / 44100
    tone = (0.1 * np.sin(2 * np.pi * 440 * t) * 32767).astype(np.int16)
    path = folder / "tone.wav"
    with wave.open(str(path), "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(44100)
        wav.writeframes(tone.tobytes())
    winsound.PlaySound(str(path), winsound.SND_FILENAME)


def _describe(path: Path) -> str:
    with wave.open(str(path), "rb") as wav:
        samples = np.frombuffer(wav.readframes(wav.getnframes()), dtype=np.int16)
        duration = wav.getnframes() / wav.getframerate()
    peak_db = rms_db(samples.astype(np.float32) / 32768)
    return f"{path.name}: {duration:.3f} s, {len(samples)} samples, RMS {peak_db:.1f} dBFS"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seconds", type=float, default=10.0)
    parser.add_argument("--tone", action="store_true", help="play a test tone for the loopback")
    parser.add_argument("--only", choices=("mic", "system"), help="capture a single track")
    args = parser.parse_args()

    folder = Path(tempfile.mkdtemp(prefix="vozata-smoke-"))
    clock = SessionClock()
    mic, loopback = default_input(), default_loopback()
    for name, device in (("mic", mic), ("system", loopback)):
        print(f"{name}: {device.id} {device.name!r} {device.channels} ch @ {device.sample_rate} Hz")

    devices = {"mic": mic, "system": loopback}
    names = [args.only] if args.only else list(devices)
    writers = {name: AlignedWavWriter(folder / f"{name}.wav", RATE) for name in names}
    sources = {name: WasapiSource(devices[name], clock, RATE) for name in names}
    clock.start()
    for name, source in sources.items():
        source.start(writers[name].write)
    if args.tone:
        threading.Thread(target=_play_tone, args=(folder,), daemon=True).start()
    time.sleep(args.seconds)
    total = clock.now()
    for source in sources.values():
        source.stop()

    total = max(total, *(writer.samples_written / RATE for writer in writers.values()))
    for writer in writers.values():
        writer.finalize(total)
    print(f"folder: {folder}")
    for name in writers:
        print(_describe(folder / f"{name}.wav"))
    for name, source in sources.items():
        print(f"{name} overflows: {source.overflows}")


if __name__ == "__main__":
    main()
