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
| `minutes/prompts.py` | include the glossary ("use these spellings") when present |
| API | `GET|PUT /vocabulary`; `vocabulary` field in `POST /sessions` |
| `config.py`, `.env.example` | `VOCABULARY_FILE` (default `vocabulary.txt` next to `.env`) |

**UI**: settings tab "Vocabulary" (list editor with add/remove/import from text); on the Start
screen an expander "Terms for this meeting" (comma or newline separated).

## Design notes

- Too many hints degrade accuracy: cap at `max_chars`, keep session terms first.

## Acceptance criteria

- [ ] Tests: store parsing (comments, blanks, duplicates), hint building and truncation order,
      hints reach `FakeTranscriber`, glossary appears in the minutes prompt, API round trip.
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
