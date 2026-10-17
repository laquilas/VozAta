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

- [ ] Tests: repository validation (missing language → error), each template renders a prompt in each
      language, unknown template → 422, template persisted in `session.json`.
- [ ] UI tests: template list loaded, selection sent on start and regenerate.
- [ ] Manual: the same transcript regenerated as `daily` and `client` gives clearly different minutes.
- [ ] Resource parity test passes.

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
- **Status:** in progress
- **Updated:** 2026-10-17 13:10
- **Next step:** UI — template ComboBox on the Start screen (`MainViewModel.Templates` /
  `SelectedTemplate`, preselect `MINUTES_TEMPLATE`, send it in `StartSessionRequest`) and in the
  regenerate action (`SessionDetailViewModel`, only around the regenerate button); tests in
  `TemplateSelectionTests.cs`.

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
- [x] UI client: `GetTemplatesAsync`, template in start and regenerate requests — this commit
- [ ] UI: template ComboBox on the Start screen and in the regenerate action
- [ ] Docs (architecture, api-contract), acceptance criteria, manual check recipe

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
