"""Manual smoke check for minutes generation (phase 04).

Generates minutes for a short synthetic meeting with the configured Ollama server and model, in
each app language (en, pt-BR, es), and prints them. Needs Ollama running and the model pulled.

Run from `engine/`:  ../.venv/Scripts/python scripts/smoke_minutes.py [--max-chars N]
"""

from __future__ import annotations

import argparse
import time

from vozata.config import load_settings
from vozata.domain import AppLanguage, Channel, ConversationLanguage, TranscriptSegment
from vozata.i18n import TomlLocalizer
from vozata.labels import SpeakerLabeler
from vozata.llm.ollama import OllamaLanguageModel
from vozata.minutes.generator import MinutesGenerator

MEETING = [
    ("mic", 2, "Good morning. Let's review the release plan for the beta."),
    ("system", 9, "The installer is ready, but the crash recovery tests are still failing."),
    ("mic", 17, "Then we postpone the beta from Friday to next Tuesday."),
    ("system", 24, "Agreed. I will fix the recovery tests by Monday."),
    ("mic", 31, "Ana will update the release notes, due Monday as well."),
    ("system", 38, "We still need to decide whether to support macOS in this release."),
]


def _segments() -> list[TranscriptSegment]:
    return [
        TranscriptSegment(
            f"{speaker}-{i:06d}",
            Channel(speaker),
            speaker,
            float(start),
            float(start + 5),
            text,
            (),
        )
        for i, (speaker, start, text) in enumerate(MEETING, start=1)
    ]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--max-chars", type=int, help="override LLM_MAX_CHARS (forces map-reduce)")
    args = parser.parse_args()

    settings = load_settings()
    llm = OllamaLanguageModel(settings.ollama_url, settings.ollama_model)
    print(f"model: {settings.ollama_model} at {settings.ollama_url}")
    if not llm.is_available():
        raise SystemExit("Ollama is not running or the model is not pulled")
    for language in AppLanguage:
        localizer = TomlLocalizer(language)
        generator = MinutesGenerator(llm, localizer, args.max_chars or settings.llm_max_chars)
        started = time.monotonic()
        minutes = generator.generate(
            _segments(), SpeakerLabeler(localizer), ConversationLanguage.EN
        )
        print(f"\n===== {language} ({time.monotonic() - started:.1f} s) =====\n{minutes}")
    llm.close()


if __name__ == "__main__":
    main()
