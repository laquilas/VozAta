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

- [ ] Tests: store parsing (comments, blanks, duplicates), hint building and truncation order,
      hints reach `FakeTranscriber`, glossary appears in the minutes prompt, API round trip;
      context prompt per channel (truncation, reset on language lock, skipped after a
      repeated segment).
- [ ] UI tests: editor add/remove/import, session terms sent on start.
- [ ] Manual: a meeting mentioning an unusual name is transcribed correctly with the term and
      incorrectly without it (note in the PR).
- [ ] Resource parity test passes.

## Tests

`tests/test_vocabulary.py`, `tests/api/test_vocabulary.py`, `VocabularyViewModelTests.cs`.

## Out of scope

Automatic term extraction from previous meetings.

## Kickoff prompt

> Execute phase 19 of the roadmap (`docs/roadmap/phases/19-custom-vocabulary.md`), following
> `docs/roadmap/README.md`.

## Progress

- **Branch:** `feature/19-custom-vocabulary`
- **Status:** in progress
- **Updated:** 2026-10-17 13:53
- **Next step:** add `transcription/context.py` (`RollingContext`) with tests, then the `prompt` argument and `avg_logprob` on the transcriber port.

### Steps

- [x] `vocabulary.py`: store (comments, blanks, case-insensitive dedupe), merge, `build_hints`
- [x] `VOCABULARY_FILE` / `CONTEXT_PROMPT_CHARS` in `config.py`, `settings_fields.py`, `.env.example`
- [ ] Rolling context prompt (`transcription/context.py`) wired into the stitcher; `prompt` and
      `avg_logprob` on the transcriber port; faster-whisper `initial_prompt` +
      `hallucination_silence_threshold`; OpenAI-compatible `prompt`
- [ ] Session: merge global + session terms → `session.json.vocabulary`, hints to every
      `transcribe` call
- [ ] Minutes prompt glossary (live stop and regeneration)
- [ ] API: `GET|PUT /vocabulary`, `vocabulary` in `POST /sessions`
- [ ] UI: client + DTOs, settings tab "Vocabulary", Start screen "Terms for this meeting"
- [ ] Docs (architecture, api-contract), acceptance criteria, manual check recipe

### Decisions and notes
- `VOCABULARY_FILE` is a `path` setting; empty (`None`) resolves in `bootstrap.py` to `vocabulary.txt` next to the `.env` file the engine reads.
