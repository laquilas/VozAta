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
