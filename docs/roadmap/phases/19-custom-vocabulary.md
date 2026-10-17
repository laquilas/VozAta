# Phase 19 — Custom vocabulary

## Goal

Improve recognition of names, acronyms and product terms with a global glossary plus per-session
terms, passed to the speech-to-text model as hints and to the minutes prompt for correct spelling.

## Depends on

06, 10

## Read first

- `engine/CLAUDE.md`, `ui/CLAUDE.md`
- [architecture.md](../architecture.md) §5 (`Transcriber.transcribe(..., hints)`), §8
  (`session.json.vocabulary`), §9 (`VOCABULARY_FILE`)
- [api-contract.md](../api-contract.md) — `GET|PUT /vocabulary`, `POST /sessions.vocabulary`

## Scope

**Engine**

| File | Content |
|------|---------|
| `vocabulary.py` | `VocabularyStore(path)`: read/write one term per line, `#` comments, dedupe case-insensitively; `build_hints(terms, max_chars=500) -> str | None` |
| `session.py` / `bootstrap.py` | merge global + session terms → `session.json.vocabulary`; pass `hints` to every `transcribe` call (faster-whisper `hotwords`; OpenAI-compatible `prompt`) |
| `transcription/context.py` | rolling context prompt ([optimizations.md](../optimizations.md) O4): per channel, the last `CONTEXT_PROMPT_CHARS` of committed text (cut on a word boundary) plus the vocabulary, passed as `initial_prompt` (`condition_on_previous_text` stays off); cleared when the language locks or after a long silence; skipped for the next chunk after a repeated segment or a very low `avg_logprob`; set `hallucination_silence_threshold` |
| `minutes/prompts.py` | include the glossary ("use these spellings") when present |
| API | `GET|PUT /vocabulary`; `vocabulary` field in `POST /sessions` |
| `config.py`, `.env.example` | `VOCABULARY_FILE` (default `vocabulary.txt` next to `.env`), `CONTEXT_PROMPT_CHARS` (200, 0 = off) |

**UI**: settings tab "Vocabulary" (list editor with add/remove/import from text); on the Start
screen an expander "Terms for this meeting" (comma or newline separated).

## Design notes

- Too many hints degrade accuracy: cap at `max_chars`, keep session terms first.

## Acceptance criteria

- [x] Tests: store parsing (comments, blanks, duplicates), hint building and truncation order,
      hints reach `FakeTranscriber`, glossary appears in the minutes prompt, API round trip;
      context prompt per channel (truncation, reset on language lock, skipped after a
      repeated segment).
- [x] UI tests: editor add/remove/import, session terms sent on start.
- [x] Manual: a meeting mentioning an unusual name is transcribed correctly with the term and
      incorrectly without it (note in the PR). — verified 2026-10-17 on the GPU (see Progress).
- [x] Resource parity test passes.

## Tests

`tests/test_vocabulary.py`, `tests/api/test_vocabulary.py`, `VocabularyViewModelTests.cs`.

## Out of scope

Automatic term extraction from previous meetings.

## Kickoff prompt

> Execute phase 19 of the roadmap (`docs/roadmap/phases/19-custom-vocabulary.md`), following
> `docs/roadmap/README.md`.

## Progress

- **Branch:** `feature/19-custom-vocabulary`
- **Status:** ready for PR
- **Updated:** 2026-10-17 18:00
- **Next step:** none (phase done). Manual check 2026-10-17 (TTS "Microsoft Maria Desktop",
  `large-v3` on CUDA): without hints "Hoje a Juscelia Trombetta apresenta o projeto Xilofonia para a
  equipe da Vozata."; with `build_hints(['Jucélia Trombetta','Xylofonia','VozAta'])` "Hoje a Jucélia
  Trombetta apresenta o projeto Xylofonia para a equipe da VozAta." (the context prompt alone gave
  the same spelling).

### Steps

- [x] `vocabulary.py`: store (comments, blanks, case-insensitive dedupe), merge, `build_hints`
- [x] `VOCABULARY_FILE` / `CONTEXT_PROMPT_CHARS` in `config.py`, `settings_fields.py`, `.env.example`
- [x] Rolling context prompt (`transcription/context.py`) wired into the stitcher; `prompt` and
      `avg_logprob` on the transcriber port; faster-whisper `initial_prompt` +
      `hallucination_silence_threshold`; OpenAI-compatible `prompt`
- [x] Session: merge global + session terms → `session.json.vocabulary`, hints to every
      `transcribe` call
- [x] Minutes prompt glossary (live stop and regeneration)
- [x] API: `GET|PUT /vocabulary`, `vocabulary` in `POST /sessions`
- [x] UI: client + DTOs, settings tab "Vocabulary", Start screen "Terms for this meeting"
- [x] Docs (architecture, api-contract), acceptance criteria, manual check recipe

### Decisions and notes
- `VOCABULARY_FILE` is a `path` setting; empty (`None`) resolves in `bootstrap.py` to `vocabulary.txt` next to the `.env` file the engine reads.
- `RollingContext` (transcription/context.py) is done; a long silence is 30 s and a very low `avg_logprob` is < -1.0 (constants in the module).
- Port: `Transcriber.transcribe(samples, language, hints=None, prompt=None)`; `prompt` is the rolling context only. faster-whisper sends the vocabulary as `hotwords` and the context as `initial_prompt` (both land in the same decoder prompt), OpenAI-compatible joins them into one `prompt` field. `TranscriptionResult.avg_logprob` (mean of segments, None when unknown).
- `session.json.vocabulary` is always written at start (an empty list when there are no terms). An unreadable glossary file is logged and the session continues with its own terms.
- The glossary is a separate `minutes.glossary` locale block added after the template instructions in the single, map and reduce prompts; templates (phase 20) are untouched.
- `GET|PUT /vocabulary` answer `503 vocabulary_failed` when the file cannot be read or saved; PUT returns the cleaned terms. The route resolves the path on every call, so a `VOCABULARY_FILE` saved in settings applies at once.
- UI: the "Vocabulary" editor is a card on the Settings page (add / remove chips / import pasted text, each change saved with PUT); the Start screen has an expander "Terms for this meeting" (comma, semicolon or newline separated), sent as `vocabulary` only when non-empty.

### Manual check recipe (pending: run on the reference machine, one phase at a time)

Offline, no microphone. From the repo root in PowerShell:

1. Make a TTS WAV with an unusual name (16 kHz mono):

   ```powershell
   Add-Type -AssemblyName System.Speech
   $s = New-Object System.Speech.Synthesis.SpeechSynthesizer
   $s.SelectVoice("Microsoft Maria Desktop")
   $fmt = New-Object System.Speech.AudioFormat.SpeechAudioFormatInfo(16000, [System.Speech.AudioFormat.AudioBitsPerSample]::Sixteen, [System.Speech.AudioFormat.AudioChannel]::Mono)
   $s.SetOutputToWaveFile("$env:TEMP\vozata19.wav", $fmt)
   $s.Speak("Bom dia. Hoje a Jucélia Trombetta apresenta o projeto Xylofonia para a equipe da Vozata.")
   $s.Dispose()
   ```

2. Transcribe it with and without the hint (GPU, `large-v3`, offline cache):

   ```powershell
   $env:HF_HUB_OFFLINE = "1"; $env:PYTHONPATH = "engine/src"
   .venv/Scripts/python -c "import wave,numpy as np; from vozata.config import Settings; from vozata.transcription.faster_whisper import FasterWhisperTranscriber as T; from vozata.vocabulary import build_hints; w=wave.open(r'$env:TEMP\vozata19.wav'); a=np.frombuffer(w.readframes(w.getnframes()),np.int16).astype(np.float32)/32768; t=T(Settings(whisper_model='large-v3')); f=lambda r:''.join(x.text for x in r.words); print('WITHOUT:', f(t.transcribe(a,'pt'))); print('WITH:   ', f(t.transcribe(a,'pt',build_hints(['Jucélia Trombetta','Xylofonia','VozAta'])))); print('CONTEXT:', f(t.transcribe(a,'pt',None,'Jucélia Trombetta falou do Xylofonia.')))"
   ```

   Expected: `WITHOUT` misspells at least one of *Jucélia Trombetta* / *Xylofonia* / *VozAta*; `WITH`
   spells them as in the glossary. Paste both lines in the PR.
3. Optional end to end: put the three terms in the settings card "Vocabulary", record while
   playing the WAV through the speakers, check `session.json.vocabulary` and the spelling in
   `transcript.md` and `minutes.md`.
