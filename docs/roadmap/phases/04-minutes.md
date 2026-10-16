# Phase 04 — Minutes generation

## Goal

Generate localized meeting minutes from a transcript with an LLM behind the `LanguageModel` port,
using Ollama as the default provider.

## Depends on

01

## Read first

- `engine/CLAUDE.md`
- [architecture.md](../architecture.md) §5 (`LanguageModel`), §9 (keys owned by 04), §10 (i18n),
  §12 (minutes)

## Scope

| File | Content |
|------|---------|
| `llm/ollama.py` | `OllamaLanguageModel(url, model, timeout=300)` with httpx: `generate(system, prompt, json_schema=None)` → `POST /api/chat` (`stream: false`, `format: json_schema` when given, `options.num_ctx = 8192`); `stream(system, prompt)` yields text from the NDJSON stream; `is_available()` → `GET /api/tags` and checks the model is pulled |
| `minutes/prompts.py` | builds system + user prompts from locale keys (`minutes.system`, `minutes.instructions`, `minutes.section.*`, `minutes.map_instructions`), stating conversation language and output language |
| `minutes/generator.py` | `MinutesGenerator(llm, localizer, max_chars)`: `generate(segments, labeler, conversation_language) -> str` (markdown); map-reduce when the rendered transcript exceeds `LLM_MAX_CHARS`, splitting at segment boundaries |
| `locales/*.toml` | minutes prompt texts and section headings in en / pt-BR / es |
| `tests/fakes.py` | `FakeLanguageModel` recording calls and returning scripted text |

## Design notes

- Add `is_available()` to the `LanguageModel` port (used by `/health` in phase 06).
- Sections (localized): Context, Summary, Topics, Decisions, Action items (owner, due date),
  Open issues. Instruct the model to not invent facts and to write "—" for empty sections.
- `LLM_PROVIDER`, `OLLAMA_URL`, `OLLAMA_MODEL`, `LLM_MAX_CHARS` added to `config.py`/`.env.example`.
- Default model `qwen2.5:7b` (~4.7 GB) fits the 6 GB GPU only when Whisper is released first
  (enforced in phase 05). Document a smaller alternative (e.g. a 3–4B model) in `.env.example`.
- **Manual setup (document in the PR)**: install Ollama for Windows, `ollama pull qwen2.5:7b`.
- LLM errors raise a dedicated `LanguageModelError`; the caller decides (phase 05 logs and keeps
  the session).

## Acceptance criteria

- [ ] Ollama client tested with `httpx.MockTransport`: request body, JSON-schema `format`,
      streaming parse, timeout and HTTP errors → `LanguageModelError`, `is_available()`.
- [ ] Generator tests: single pass under the limit, map-reduce over the limit (N map calls + 1
      reduce), headings in the selected app language, prompt mentions both languages.
- [ ] Manual run against a local Ollama on a sample transcript produces sensible minutes in each
      of en / pt-BR / es (note results in the PR).
- [ ] Locale parity test still passes; coverage ≥ 80 %.

## Tests

`tests/llm/test_ollama.py`, `tests/minutes/test_generator.py`, `tests/minutes/test_prompts.py`.

## Out of scope

Templates (20), action-item extraction (23), Q&A (24), triggering at session end (05).

## Kickoff prompt

> Execute phase 04 of the roadmap (`docs/roadmap/phases/04-minutes.md`), following
> `docs/roadmap/README.md`.

## Progress

- **Branch:** `feature/04-minutes`
- **Status:** in progress
- **Updated:** 2026-10-15 23:31
- **Next step:** TDD `minutes/generator.py`: `tests/minutes/test_generator.py` (single pass under `LLM_MAX_CHARS`, segments sorted and rendered with labels, map-reduce over the limit with N map calls + 1 reduce split at segment boundaries, an oversized single line is its own part, empty transcript raises, `LanguageModelError` propagates), see it fail, then implement.

### Steps

- [x] Start phase: status `in progress`, Progress section — `1b216a7`
- [x] Config keys owned by 04 + `.env.example` note on a smaller model — `e7d1bea`
- [x] `LanguageModelError` + `llm/ollama.py` (`OllamaLanguageModel`, tested with `httpx.MockTransport`) — `6eed588`
- [x] Locale keys + `minutes/prompts.py`
- [ ] `minutes/generator.py` (`MinutesGenerator`, map-reduce)
- [ ] Manual run against a local Ollama in en / pt-BR / es
- [ ] Verify; tick acceptance criteria; set phase `done`

### Decisions and notes

- `is_available()` is already part of the `LanguageModel` port (added in phase 01).
- `LanguageModelError` lives in `ports.py` next to the port: callers catch it by port, not by provider.
- Prompts name languages through locale keys (`languages.*`, `minutes.output_language`), so each locale names them in its own language.
- **Ollama is not installed** on the reference machine; the manual run waits for the user's approval to install it and pull `qwen2.5:7b` (~4.7 GB).
