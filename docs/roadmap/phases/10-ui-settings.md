# Phase 10 — UI settings

## Goal

Edit engine settings from the UI (instead of `.env`), choose the app language and the default
conversation language, and see engine / GPU / LLM status.

## Depends on

07

## Read first

- `ui/CLAUDE.md` and `engine/CLAUDE.md`
- [api-contract.md](../api-contract.md) — `GET|PUT /settings`, `GET /health`
- [architecture.md](../architecture.md) §9 (keys, secrets), §10 (languages)

## Scope

**Engine**

| File | Content |
|------|---------|
| `api/routes/settings.py` | `PUT /settings`: validate with `config.py`, persist to `.env` with `python-dotenv` `set_key` (keeps comments/order), return `restart_required` |
| `config.py` | per-key flag `applies`: `next_session` (most keys) or `restart` (`API_HOST`, `API_PORT`, `STT_PROVIDER`, `WHISPER_*`); masked secrets are not overwritten when the UI sends `"********"` |

**UI**

| Item | Content |
|------|---------|
| `ViewModels/SettingsViewModel.cs` | builds editors from the settings `schema` (int/float → NumericUpDown, enum → ComboBox, bool → ToggleSwitch, string, secret → password box), grouped by area; Save / Discard; shows which keys need a restart and offers "Restart engine" via `IEngineProcess` |
| App language | selector `en` / `pt-BR` / `es` — applies to the UI immediately and saves `APP_LANGUAGE` |
| Conversation language | default `TRANSCRIPTION_LANGUAGE` (`en`, `pt`, `es`, `auto`) used by the Start screen |
| `ViewModels/HealthViewModel.cs` | GPU name/VRAM, STT provider/model/device, LLM provider/model/reachable; "Check again" button |
| Resources | localized labels and help text for every setting key |

## Acceptance criteria

- [ ] Engine tests: valid update persisted to a temp `.env` preserving comments, invalid value → 422
      with the key, secrets mask round-trip, `restart_required` correct.
- [ ] UI tests: editors generated per type, dirty tracking, save/discard, language switch applied,
      restart prompt.
- [ ] Manual: change `CHUNK_SECONDS` to 8 in the UI → next session uses 8 s windows.
- [ ] Resource parity test passes.

## Tests

`engine/tests/api/test_settings_put.py`, `SettingsViewModelTests.cs`, `HealthViewModelTests.cs`.

## Out of scope

Vocabulary editor (19), template selection (20).

## Kickoff prompt

> Execute phase 10 of the roadmap (`docs/roadmap/phases/10-ui-settings.md`), following
> `docs/roadmap/README.md`.

## Progress

- **Branch:** `feature/10-ui-settings`
- **Status:** in progress
- **Updated:** 2026-10-16 18:10
- **Next step:** `ViewModels/SettingsViewModel.cs` + `SettingEditorViewModel` (editor kind from schema type, text / number / bool / choice / secret values, dirty tracking, Save sends only changed keys, Discard, per-key error from `invalid_setting`, restart prompt via `IEngineProcess.RestartAsync`, saved values reported to the main window) with `SettingsViewModelTests.cs`

### Steps

- [x] Start the phase (README status, Progress section)
- [x] Schema: `group` and `applies` per key — `06fe8ca`
- [x] Engine: `SettingsFile` (validate, persist with `set_key`, secrets mask, restart keys) +
      `PUT /settings` (422 `invalid_setting` with `key`); sessions / minutes / LLM check read the
      current settings — `ba6ed5e`
- [x] UI client: `UpdateSettingsAsync`, schema fields, `IEngineProcess.RestartAsync` — `53e1470`
- [x] `HealthViewModel` (status bar + settings page, "Check again") — this commit
- [ ] `SettingsViewModel` + typed editors (dirty tracking, save / discard, restart prompt)
- [ ] Localized label and help for every key (en / pt-BR / es)
- [ ] Settings tab in the main window; app language saved; default conversation language applied
- [ ] Manual: `CHUNK_SECONDS` = 8 in the UI → next session uses 8 s windows; criteria

### Decisions and notes

- Most keys apply to the **next session** without a restart: the API keeps the current settings in
  a `SettingsFile` that sessions, minutes jobs and the LLM health check read. Keys read once at
  start-up need an engine restart: `API_HOST`, `API_PORT`, `STT_PROVIDER`, `WHISPER_*`,
  `OUTPUT_DIR`, `SAMPLE_RATE`.
- `.env` is updated key by key with `dotenv.set_key` (comments and order kept). A value also set
  as a process environment variable keeps winning over `.env` (documented behaviour of
  `config.py`).
- The masked secret value (`********`) sent back by the UI means "unchanged".
