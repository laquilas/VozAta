# Phase 01 — Engine core

## Goal

Create the pure, dependency-free core every other engine phase builds on: domain types, ports,
settings, localization, speaker labels and formatting helpers.

## Depends on

00

## Read first

- [standards.md](../standards.md) (engine section) or `engine/CLAUDE.md`
- [architecture.md](../architecture.md) §3 (SOLID), §4 (domain), §5 (ports), §8 (data model),
  §9 (config keys owned by 01), §10 (i18n)

## Scope

| File | Content |
|------|---------|
| `domain.py` | enums and frozen dataclasses from architecture §4 (only those needed now: `Channel`, `SessionStatus`, `AppLanguage`, `ConversationLanguage`, `AudioChunk`, `Word`, `TranscriptionResult`, `TranscriptSegment`) + `TranscriptSegment.to_dict()/from_dict()` matching the jsonl schema |
| `ports.py` | `AudioSource`, `AudioSink`, `Transcriber`, `TranscriptSink`, `AudioMixer`, `LanguageModel`, `Localizer` |
| `config.py` | `Settings` (frozen) + `load_settings(env: Mapping[str, str] | None = None, env_file: Path | None = None)`; keys owned by 01: `CHUNK_SECONDS`, `SAMPLE_RATE`, `APP_LANGUAGE`, `TRANSCRIPTION_LANGUAGE`, `MIC_LABEL`, `SYSTEM_LABEL`, `OUTPUT_DIR`; `ConfigError` with a message naming the key and the allowed values |
| `i18n.py` | `TomlLocalizer(language)` implementing `Localizer` (stdlib `tomllib`), fallback to `en` for a missing key only in non-test runs (tests enforce parity) |
| `locales/en.toml`, `locales/pt-BR.toml`, `locales/es.toml` | `labels.mic`, `labels.system`, `labels.user` (`"User {n}"`), `errors.*` for config errors |
| `labels.py` | `SpeakerLabeler(localizer, mic_override, system_override, names: Mapping[str, str])`: `label(speaker_id) -> str` (`mic`, `system`, `system:<n>`) |
| `formatting.py` | `format_timestamp(seconds) -> "hh:mm:ss"`, `render_line(segment, label) -> "[hh:mm:ss] Label: text"` |
| `language.py` | `resolve_conversation_language(settings, requested: str | None) -> ConversationLanguage` (`pt-BR` → `pt`) and `to_whisper_code(lang) -> str | None` (`auto` → `None`) |

## Design notes

- `Settings` groups keys by area with nested frozen dataclasses only if it stays readable; later
  phases add their keys here (each phase owns the keys listed in architecture §9).
- Numeric validation: `CHUNK_SECONDS` in `[1, 60]`, `SAMPLE_RATE` = 16000 only (Whisper
  requirement) — fail fast otherwise.
- Settings must be constructible from a plain dict in tests (no `.env` needed).
- Locale keys: flat dotted names, `{param}` placeholders via `str.format_map`.

## Acceptance criteria

- [x] All modules above exist with type hints; no I/O in `domain.py`.
- [x] Invalid config values raise `ConfigError` naming the key and allowed values.
- [x] Key-parity test passes for the three locales.
- [x] `SpeakerLabeler` returns `Me`/`Eu`/`Yo` and `User 2`/`Usuário 2`/`Usuario 2` per language;
      overrides and names win over defaults.
- [x] Coverage ≥ 80 %; ruff clean.

## Tests

`tests/test_config.py` (defaults, each invalid value, env-file loading, empty
`TRANSCRIPTION_LANGUAGE` derivation), `tests/test_i18n.py` (parity, placeholders),
`tests/test_labels.py`, `tests/test_formatting.py`, `tests/test_language.py`,
`tests/test_domain.py` (jsonl round trip).

## Out of scope

Audio, transcription, LLM, providers registries (phase 05 `bootstrap.py`).

## Kickoff prompt

> Execute phase 01 of the roadmap (`docs/roadmap/phases/01-engine-core.md`), following
> `docs/roadmap/README.md`.

## Progress

- **Branch:** `feature/01-engine-core`
- **Status:** ready for PR
- **Updated:** 2026-10-15 22:56
- **Next step:** none; open the PR (`pr-ready` → `pr-open` → `pr-review`) and merge after CI on the PR is green.

### Steps

- [x] Start phase: status `in progress`, Progress section — `7e96b07`
- [x] `domain.py` + `tests/test_domain.py` (jsonl round trip) — `33818b1`
- [x] `ports.py` + `tests/fakes.py` + structural port tests; coverage ignores `...` bodies — `30131cf`
- [x] `i18n.py` + `locales/{en,pt-BR,es}.toml` + package data; parity and placeholder tests — `3273324`
- [x] `config.py` (`Settings`, `load_settings`, `ConfigError`) + `tests/test_config.py` — `e80faa9`, `0734822`
- [x] `labels.py` (`SpeakerLabeler`) + `tests/test_labels.py` — `579fab8`
- [x] `formatting.py` + `tests/test_formatting.py` — `07e3044`
- [x] `language.py` + `tests/test_language.py` — `4e98e96`
- [x] Verify; tick acceptance criteria; set phase `done`

### Decisions and notes

- **`ConfigError` localization**: config errors can happen before a localizer exists (`APP_LANGUAGE` may itself be invalid). `ConfigError` carries a message key and params; `str()` renders with the `en` locale and `render(localizer)` renders in any language, so no text is hard-coded.
- **`AudioChunk`** is `frozen=True, eq=False`: dataclass equality on `np.ndarray` fields is ambiguous.
- **Ports** are `@runtime_checkable` Protocols; `tests/fakes.py` provides fakes, and structural `isinstance` tests check them. Coverage excludes `...`-only lines (Protocol bodies).
- `pyproject.toml` sets pytest `pythonpath = ["."]` so tests import shared fakes as `tests.fakes`.
- **`Localizer.t(key, /, **params)`**: `key` is positional-only so a placeholder may itself be called `key` (config errors use `{key}`); architecture §5 updated.
- `load_settings()` without arguments reads `.env` in the working directory, then the process environment on top; with an `env` mapping, only `env_file` (if given) sits underneath it. Empty values mean "not set".
- Verification: 86 tests, 100 % coverage, ruff check and format clean.
