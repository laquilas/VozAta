# Phase 38 — Config page redesign

## Goal

Make every setting easy to find and hard to get wrong: a Config page with sections and search,
real choice lists for providers and models, a folder picker, "Test" buttons for external services
and a Storage section. The `.env` file stays the source of the engine settings.

## Depends on

35

## Read first

- `ui/CLAUDE.md`, `engine/CLAUDE.md`
- [architecture.md](../architecture.md) §9 (config keys)
- [api-contract.md](../api-contract.md) — `GET /settings`, `PUT /settings`
- `engine/src/vozata/settings_fields.py`, `ui/.../ViewModels/SettingsViewModel.cs`,
  `SettingEditorViewModel.cs`, `Views/SettingsView.axaml`

## Scope

**Engine**

| File | Content |
|------|---------|
| `settings_fields.py` | each field may declare `options_source`: `stt_providers`, `llm_providers`, `diarization_providers`, `translation_providers` (from the bootstrap registries), `whisper_models` (known list + cached models found in the HF cache), `ollama_models` (`/api/tags` of `OLLAMA_HOST`), `compute_types`, `devices` |
| API | `GET /settings/options` → `{source: [{value, label, available}]}` (unreachable Ollama → empty list + `reachable: false`, never an error); `POST /settings/test/{target}` for `ollama`, `stt_api`, `hf_token` (HEAD on the pyannote models, reports "terms not accepted" on 403), `azure_devops`, `github` → `{ok, message}` localized; uses the **saved** settings, secrets never echoed or logged |
| Storage info | `GET /health` → `storage: {backend, database_path, size_bytes, audio_cache_bytes, warning}` (phases 31/32) |

**UI**

| File | Content |
|------|---------|
| `Views/ConfigPage.axaml` | left: section list (General, Audio, Segmentation, Transcription, Speakers, Minutes, Tasks, API — from FIELDS groups — plus Desktop app, Vocabulary, Storage, About); top: search box that filters keys by label, key name and help text across sections; right: the editors of the selected section in cards |
| `SettingEditorViewModel.cs` | `choice` editors fed by `options_source` (editable combo: a value not in the list is kept and flagged "not installed"); `path` → text + "Browse…" folder picker (`IStorageProvider`); `url` → validated on edit; secrets → password box with "Replace" (never shows the stored value) |
| Badges | "Restart needed" per key (from `applies`), "Changed" until saved; sticky Save / Discard bar when dirty; restart banner as today |
| Test buttons | next to the Ollama host, STT API, HF token, Azure DevOps and GitHub sections; result inline (✓ / error text) |
| Storage section | backend, database path (open folder), database size, audio cache size with "Clear cache", OneDrive warning |
| About | versions (app, engine), GPU, models, links to the licenses |
| Resources | strings for sections, badges, tests and storage in en / pt-BR / es |

## Design notes

- The 62 keys are already exposed; this phase changes how they are presented and validated, not
  where they are stored. Keys stay generated from `GET /settings` — no hand-written per-key UI.
- Saving only sends changed keys (unchanged behavior); `.env` comments and order are preserved by
  `SettingsFile`.
- Tests that call out run only on demand; the page never contacts a service on open, except
  `GET /settings/options` (local Ollama `/api/tags`, 2 s timeout).

## Acceptance criteria

- [ ] Engine tests: options per source (fakes for registries, HF cache dir, Ollama tags via
      `httpx.MockTransport`), every test target with success / auth error / unreachable, secrets
      absent from responses and logs.
- [ ] UI tests: section navigation, search filtering across sections, choice editor with an
      unknown value, folder picker (fake), URL validation, dirty/save/discard, test button states,
      storage section values.
- [ ] Manual: change the Whisper model from the list, the Ollama model from the installed ones,
      pick an output folder, test Ollama and the HF token (✓), restart banner after a restart key.
- [ ] Resource parity test and the `.env.example` label test pass.

## Tests

`tests/api/test_settings_options.py`, `tests/api/test_settings_test.py`,
`ConfigPageViewModelTests.cs`, `SettingEditorViewModelTests.cs`.

## Out of scope

Moving settings into the database (they stay in `.env`), per-user profiles, import/export of
settings.

## Kickoff prompt

> Execute phase 38 of the roadmap (`docs/roadmap/phases/38-config-page.md`), following
> `docs/roadmap/README.md`.

## Progress

- **Branch:** `feature/38-config-page`
- **Status:** in progress
- **Updated:** 2026-10-17 14:30
- **Next step:** Tick the acceptance criteria, set the README status to done, write the manual check recipe, run the full engine + UI suites, open the PR.

### Steps

- [x] Engine: `options_source` per field + `GET /settings/options` (registries, Whisper models + HF cache, Ollama tags, compute types, devices)
- [x] Engine: `POST /settings/test/{target}` (ollama, stt_api, hf_token, azure_devops, github)
- [x] Engine: `GET /health` storage sizes + `DELETE /storage/cache`
- [x] UI client: DTOs and `IEngineClient` methods for options, tests, storage
- [x] UI: editor kinds (options combo, path + Browse, url validation, secret Replace/Remove, Changed badge)
- [x] UI: `ConfigPageViewModel` sections + search, test buttons, Storage and About sections
- [x] UI: `ConfigPage.axaml` (sections list, search, cards, sticky Save / Discard bar) + screenshots
- [ ] Docs (api-contract, architecture §9), full suites, PR

### Decisions and notes

- Options response shape: `{options: {source: [...]}, reachable: {source: bool}}` (the phase file's `{source: [...]}` plus `reachable: false`, folded into one typed object for the C# client).
- `GET /health` keeps phase 31's `storage.database` (not `database_path`) and adds `size_bytes` and `audio_cache_bytes`; the audio cache is `OUTPUT_DIR/cache/` as phase 32 defines it. Clear cache is `DELETE /storage/cache`.
- The phase file says `OLLAMA_HOST`; the key is `OLLAMA_URL`.
- The Config page replaces `SettingsView` (`Views/ConfigPage.axaml`); `ConfigPageViewModel` moved out of `Pages.cs`. The engine status card moved into About (with Check again).
- Secrets: Replace (empty password box) and Remove (clears the key on Save); the mask `********` never reaches a text box any more.
- Browse: `*_DIR` keys pick a folder, `*_FILE` keys a file, `DATABASE_PATH` a folder (the file name is kept, default `vozata.db`).
- Choice keys that also have an `options_source` (`WHISPER_DEVICE`, `DIARIZATION_DEVICE` → `devices`) keep their fixed list and only mark unavailable entries (cuda without a GPU).
- Options and storage load with the page at start-up (`MainViewModel.InitializeAsync` → `ConfigPageViewModel.LoadAsync`); connection tests run only on click.
