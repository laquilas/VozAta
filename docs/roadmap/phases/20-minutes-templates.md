# Phase 20 — Minutes templates

## Goal

Different meetings need different minutes. Offer templates (general, daily, one-on-one, client,
retrospective) chosen at start or when regenerating.

## Depends on

04, 07

## Read first

- `engine/CLAUDE.md`, `ui/CLAUDE.md`
- [architecture.md](../architecture.md) §10 (i18n), §12 (minutes)
- [api-contract.md](../api-contract.md) — `GET /templates`, `template` in `POST /sessions` and
  `POST /sessions/{id}/minutes`

## Scope

**Engine**

| File | Content |
|------|---------|
| `minutes/templates/<id>.toml` | one file per template with a block per language (`[en]`, `[pt-BR]`, `[es]`): `name`, `instructions`, ordered `sections` (heading + guidance) |
| `minutes/template_repository.py` | loads and validates templates (every language present, non-empty sections) |
| `minutes/generator.py` / `prompts.py` | build prompts from the selected template instead of fixed sections (general = the phase-04 sections) |
| API | `GET /templates` (localized names); template in `POST /sessions` (stored in `session.json`) and in `POST /sessions/{id}/minutes` |
| `config.py`, `.env.example` | `MINUTES_TEMPLATE` (default `general`) |

Template intent:
- **daily** — per person: done / doing / blockers.
- **one_on_one** — topics, feedback, agreements, follow-ups.
- **client** — client needs, commitments, risks, next steps, deadlines.
- **retrospective** — went well, to improve, actions.

**UI**: template ComboBox on the Start screen and in the "Regenerate minutes" action.

## Acceptance criteria

- [x] Tests: repository validation (missing language → error), each template renders a prompt in each
      language, unknown template → 422, template persisted in `session.json`.
- [x] UI tests: template list loaded, selection sent on start and regenerate.
- [ ] Manual: the same transcript regenerated as `daily` and `client` gives clearly different minutes.
      — pending manual run against Ollama (parallel wave: no Ollama/GPU checks in the session);
      exact recipe under Progress → *Manual check recipe*.
- [x] Resource parity test passes.

## Tests

`tests/minutes/test_template_repository.py`, `test_generator.py` (extended), `tests/api/test_templates.py`,
`TemplateSelectionTests.cs`.

## Out of scope

User-defined templates edited in the UI (backlog).

## Kickoff prompt

> Execute phase 20 of the roadmap (`docs/roadmap/phases/20-minutes-templates.md`), following
> `docs/roadmap/README.md`.

## Progress

- **Branch:** `feature/20-minutes-templates`
- **Status:** ready for PR
- **Updated:** 2026-10-17 14:10
- **Next step:** wait for CI on the PR, then run the manual check recipe below (needs Ollama with
  `qwen2.5:7b`) before merging.

### Steps

- [x] Template files (en, pt-BR, es) + `TemplateRepository` with validation, package data,
      PyInstaller spec check — `36ef036`
- [x] Prompts and `MinutesGenerator` built from the selected template (general = phase-04
      sections) — `216e2f9`
- [x] `MINUTES_TEMPLATE` config key (`config.py`, `settings_fields.py`, `.env.example`, settings
      page label/help and template names) — `2fb54c8`
- [x] Template stored in `session.json` at start; session minutes use it; CLI `minutes` uses it
      — `2f77bce`
- [x] API: `GET /templates`, `template` in `POST /sessions` and `POST /sessions/{id}/minutes`
      (unknown → 422 `unknown_template`); api-contract + architecture §8/§12 — `9141330`
- [x] UI client: `GetTemplatesAsync`, template in start and regenerate requests — `b60515c`
- [x] UI: template ComboBox on the Start screen and in the regenerate action — `f94206d`
- [x] Docs (architecture, api-contract), acceptance criteria, manual check recipe — this commit

### Manual check recipe

Needs Ollama running with `qwen2.5:7b` (`ollama pull qwen2.5:7b`) and one recorded session with a
real conversation (any folder under `OUTPUT_DIR`, e.g. `recordings/20261016_090000`). No audio
hardware is used: only the stored transcript is summarized.

1. From `engine/`: `../.venv/Scripts/python -m vozata serve` (wait for "API ... listening").
2. In another shell (PowerShell), pick the session id `$id` and list the templates:
   `Invoke-RestMethod http://127.0.0.1:8765/templates` → five rows, names in `APP_LANGUAGE`.
3. Daily: `Invoke-RestMethod -Method Post http://127.0.0.1:8765/sessions/$id/minutes -ContentType application/json -Body '{"template":"daily"}'`;
   wait for the `minutes_ready` event (or ~30–60 s), then
   `Copy-Item recordings/$id/minutes.md $env:TEMP/minutes-daily.md`.
   Expect: `## Updates by person` with one `###` per participant and `Done:` / `Doing:` /
   `Blockers:` bullets, then `## Blockers`, `## Follow-ups`; `session.json` has `"template": "daily"`.
4. Client: same call with `{"template":"client"}`, copy to `minutes-client.md`. Expect:
   `## Client needs`, `## Commitments`, `## Risks`, `## Next steps`, `## Deadlines`;
   `session.json` has `"template": "client"`.
5. Compare: `code --diff $env:TEMP/minutes-daily.md $env:TEMP/minutes-client.md` — different
   headings and a clearly different organization (per person vs. per commitment/risk).
6. Unknown id: `{"template":"weekly"}` → HTTP 422 `unknown_template`.
7. UI: `dotnet run --project ui/src/VozAta.Desktop`; the Start screen shows "Minutes template"
   preselected with `MINUTES_TEMPLATE`; in History, open the session: the picker next to
   "Regenerate minutes" shows `Client meeting` (stored template); pick `Daily stand-up`, click
   "Regenerate minutes" → the minutes pane reloads with the daily sections. Switch the interface
   language to Português: template names change in both pickers and the selection is kept.
8. CLI: `../.venv/Scripts/python -m vozata minutes recordings/$id` regenerates with the stored
   template (the last one used).

### Decisions and notes

- Template files carry a top-level `order` (position in `GET /templates`); ids are the file
  names. `collect_data_files("vozata")` in `packaging/engine.spec` already bundles every data file
  of the package, so the spec only needed its comment updated (a packaging test checks both the
  `package-data` glob and the spec).
- The locale keys `minutes.instructions` / `map_instructions` keep the frame (languages, Markdown,
  "—" for empty headings) and take `{template_instructions}`, `{sections}` and `{guidance}` from the
  template; the old `minutes.section.*` keys moved into `templates/general.toml`. The generator is
  built with one `LocalizedTemplate` (one generator per job) and exposes `template_id`.
- `MINUTES_TEMPLATE` is a `choice` setting whose choices are the bundled ids (a `StrEnum` built
  from `bundled_templates()` in `settings_fields.py`); `config.py` rejects unknown ids with
  `invalid_choice`. The settings page shows the names from `TemplateName_<id>` resx keys.
- `session.json.template` is written at start (also when `GENERATE_MINUTES=false`, so a later
  regeneration uses it). `write_session_minutes` takes a generator factory: requested template →
  stored template (if still bundled) → `MINUTES_TEMPLATE`; the template used is saved back to
  `session.json`. The only `session.py` change is the `SessionComponents.minutes_template` field
  (the stop sequence is untouched, phases 14/22 edit it).
- `GET /templates` names and regenerated minutes follow the *current* `APP_LANGUAGE` (after
  `PUT /settings`): the regeneration builds its localizer from the current settings, so the
  template text and the prompt frame are always in the same language.
- UI: `MinutesTemplatesViewModel` (shared by the Start screen and the session detail) keeps the
  same `TemplateOption` objects across reloads and only renames them, so pickers keep their
  selection when the language changes. The session detail change is limited to a ComboBox next to
  "Regenerate minutes", preselected from `session.json.template` (phase 22 also edits that view).
