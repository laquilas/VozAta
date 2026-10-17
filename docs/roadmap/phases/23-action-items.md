# Phase 23 — Action items export

## Goal

Extract action items (description, owner, due date) as structured data and export the selected ones
as Azure DevOps work items or GitHub issues.

## Depends on

04, 09

## Read first

- `engine/CLAUDE.md` ("Add a provider" checklist), `ui/CLAUDE.md`
- [architecture.md](../architecture.md) §4 (`ActionItem`), §5 (`LanguageModel.generate(json_schema)`,
  `TaskExporter`), §9 (keys, secrets)
- [api-contract.md](../api-contract.md) — action-items rows, `action_items_ready`

## Scope

**Engine**

| File | Content |
|------|---------|
| `minutes/action_items.py` | `ActionItemExtractor(llm, localizer)`: localized prompt + JSON schema; validates the response, one retry on invalid JSON; links items to `source_segment_ids` |
| `storage/` | `action_items.json` read/write (keeps `exported_url` per item) |
| `export/tasks/azure_devops.py` | `AzureDevOpsExporter`: `POST {AZDO_ORG_URL}/{AZDO_PROJECT}/_apis/wit/workitems/$Task?api-version=7.1` (JSON Patch: title, description with session link/time, assigned-to left empty, due date when present), Basic auth with PAT |
| `export/tasks/github.py` | `GitHubIssuesExporter`: `POST /repos/{GITHUB_REPO}/issues` with token |
| `bootstrap.py` | `TASK_EXPORTERS` registry (only configured targets are offered) |
| `session.py` | extraction after minutes when `EXTRACT_ACTION_ITEMS` is true |
| API | `POST/GET /sessions/{id}/action-items`, `POST .../export`; `action_items_ready` event |
| `config.py`, `.env.example` | `EXTRACT_ACTION_ITEMS` (`true`), `AZDO_ORG_URL`, `AZDO_PROJECT`, `AZDO_PAT`, `GITHUB_REPO`, `GITHUB_TOKEN` (secrets masked) |

**UI**: "Action items" tab: checklist with editable description/owner/due, target selector, Export
button, created links shown; already exported items are disabled (no duplicates).

## Acceptance criteria

- [ ] Tests: extractor with `FakeLanguageModel` (valid, invalid → retry → error), exporters with
      `httpx.MockTransport` (payload, auth header, error mapping), no re-export of exported items,
      only configured targets listed.
- [ ] UI tests: selection, edits sent, results displayed, disabled exported items.
- [ ] Manual: export one item to a test Azure DevOps project and one to a test GitHub repo.
- [ ] Resource parity test passes.

## Tests

`tests/minutes/test_action_items.py`, `tests/export/tasks/test_azure_devops.py`, `test_github.py`,
`tests/api/test_action_items.py`, `ActionItemsViewModelTests.cs`.

## Out of scope

Calendar invites, Jira (another `TaskExporter` later).

## Kickoff prompt

> Execute phase 23 of the roadmap (`docs/roadmap/phases/23-action-items.md`), following
> `docs/roadmap/README.md`.

## Progress

- **Branch:** `feature/23-action-items`
- **Status:** in progress
- **Updated:** 2026-10-17 10:00
- **Next step:** add the `TaskExporter` port and `export/tasks/{azure_devops,github}.py` with
  `httpx.MockTransport` tests, then the `TASK_EXPORTERS` registry in `bootstrap.py`

### Steps

- [x] Domain `ActionItem` + `storage/action_items.py` (`action_items.json`)
- [x] `minutes/action_items.py`: `ActionItemExtractor` (localized prompt, JSON schema, one retry)
- [x] Config keys `EXTRACT_ACTION_ITEMS`, `AZDO_*`, `GITHUB_*` (secrets masked) + `.env.example`
- [ ] `TaskExporter` port, `AzureDevOpsExporter`, `GitHubIssuesExporter`, `TASK_EXPORTERS` registry
- [ ] Stop step: extraction after minutes in `session.py` + `action_items_ready` event
- [ ] API: `POST/GET/PUT /sessions/{id}/action-items`, `POST .../export`
- [ ] UI: client methods + DTOs, `ActionItemsViewModel`, "Action items" tab, resources
- [ ] Docs (architecture, api-contract), acceptance criteria, full suites, PR

### Decisions and notes

- (none yet)
