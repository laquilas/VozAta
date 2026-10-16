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

- [x] Engine tests: valid update persisted to a temp `.env` preserving comments, invalid value → 422
      with the key, secrets mask round-trip, `restart_required` correct.
- [x] UI tests: editors generated per type, dirty tracking, save/discard, language switch applied,
      restart prompt.
- [x] Manual: change `CHUNK_SECONDS` to 8 in the UI → next session uses 8 s windows.
- [x] Resource parity test passes.

## Tests

`engine/tests/api/test_settings_put.py`, `SettingsViewModelTests.cs`, `HealthViewModelTests.cs`.

## Out of scope

Vocabulary editor (19), template selection (20).

## Kickoff prompt

> Execute phase 10 of the roadmap (`docs/roadmap/phases/10-ui-settings.md`), following
> `docs/roadmap/README.md`.

## Progress

- **Branch:** `feature/10-ui-settings`
- **Status:** ready for PR
- **Updated:** 2026-10-16 20:00
- **Next step:** open and merge the PR (combined draft in `__pr__/feature-10-ui-settings/`)

### Steps

- [x] Start the phase (README status, Progress section)
- [x] Schema: `group` and `applies` per key — `06fe8ca`
- [x] Engine: `SettingsFile` (validate, persist with `set_key`, secrets mask, restart keys) +
      `PUT /settings` (422 `invalid_setting` with `key`); sessions / minutes / LLM check read the
      current settings — `ba6ed5e`
- [x] UI client: `UpdateSettingsAsync`, schema fields, `IEngineProcess.RestartAsync` — `53e1470`
- [x] `HealthViewModel` (status bar + settings page, "Check again") — `43cb574`
- [x] `SettingsViewModel` + typed editors (dirty tracking, save / discard, restart prompt) — `22b9e34`
- [x] Localized label and help for every key (en / pt-BR / es) — `41e0166`
- [x] Settings tab in the main window; app language saved; default conversation language applied — `4670f4e`
- [x] Manual: `CHUNK_SECONDS` = 8 in the UI → next session uses 8 s windows; criteria — this commit

### Decisions and notes

- Most keys apply to the **next session** without a restart: the API keeps the current settings in
  a `SettingsFile` that sessions, minutes jobs and the LLM health check read. Keys read once at
  start-up need an engine restart: `API_HOST`, `API_PORT`, `STT_PROVIDER`, `WHISPER_*`,
  `OUTPUT_DIR`, `SAMPLE_RATE`.
- `.env` is updated key by key with `dotenv.set_key` (comments and order kept). A value also set
  as a process environment variable keeps winning over `.env` (documented behaviour of
  `config.py`).
- The masked secret value (`********`) sent back by the UI means "unchanged".
- **Manual check (2026-10-16, desktop app via UI Automation).** The Settings tab showed the
  engine status card and all six groups with typed editors (edit boxes, spinners, combo boxes,
  toggles), help texts and "applies after a restart" badges. Choosing `fixed` for "How audio is
  cut" and 8 for "Window length (s)", then Save, wrote `CHUNK_MODE=fixed` and `CHUNK_SECONDS=8` to
  `engine/.env` and `GET /settings` returned them; the next recording's `session.json` had
  `"CHUNK_MODE": "fixed", "CHUNK_SECONDS": 8.0`. Changing "Recognition device" (a restart key)
  showed "These settings apply after the engine restarts"; **Restart engine** replaced the engine
  process in ~5 s, the app reconnected and showed "The engine restarted with the new settings".
  `engine/.env` did not exist before the check and was deleted afterwards.
- **Fixed during the check:** one save hit "Unexpected engine error": `set_key` replaces `.env`
  through a temporary file, which fails while OneDrive (this repository's location) holds the
  file — writes are now retried and a lasting lock returns `503 settings_write_failed`. UI
  Automation read combo selections as type names — choice options now read as their label.
- UI Automation notes for next time: `NumericUpDown` needs `RangeValuePattern.SetValue` (typing
  into its edit box is only committed on Enter / focus loss); search a combo's own list items, not
  the whole desktop.
