"""The recorder process (phase 61): captures the audio of a meeting and never loses it.

It starts in about a second, long before the engine answers, and records every sample to
`OUTPUT_DIR/live/<id>/` as it comes; the engine attaches to the recording whenever it is up.

Import budget: this package may import numpy, soxr, pyaudiowpatch, python-dotenv, the standard
library and the light `vozata` modules it names (`domain`, `audio.capture`, `audio.devices`,
`audio.portaudio`, `audio.levels`, `audio.wav_writer`, `heartbeat`, `storage.wav_repair`).
Never `vozata.bootstrap`, `vozata.config`, `vozata.api`, FastAPI, faster-whisper, PyAV or httpx:
`tests/recorder/test_import_budget.py` keeps them out.
"""
