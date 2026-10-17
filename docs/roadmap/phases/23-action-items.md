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

- [x] Tests: extractor with `FakeLanguageModel` (valid, invalid → retry → error), exporters with
      `httpx.MockTransport` (payload, auth header, error mapping), no re-export of exported items,
      only configured targets listed.
- [x] UI tests: selection, edits sent, results displayed, disabled exported items.
- [ ] Manual: export one item to a test Azure DevOps project and one to a test GitHub repo —
      **pending manual (credentials)**; recipe in Progress.
- [x] Resource parity test passes.

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
- **Status:** ready for PR
- **Updated:** 2026-10-17 16:00
- **Next step:** none (phase done). Extraction checked 2026-10-17 through the API with Ollama
  `qwen2.5:7b` on a real pt-BR TTS meeting: `action_items_ready` fired and the items were Carlos (fix
  the recovery tests) and Ana (release notes), in Portuguese. The check found that the model copies
  the `[id]` brackets into `source_segment_ids`, which dropped every source; fixed by stripping them
  (sources now link to the right lines). Known model limit: "até segunda-feira" became the meeting
  date (2026-10-16) instead of Monday 2026-10-19. Export to Azure DevOps / GitHub is pending manual
  (credentials); exporting to an unconfigured target returns the localized 422.

### Steps

- [x] Domain `ActionItem` + `storage/action_items.py` (`action_items.json`)
- [x] `minutes/action_items.py`: `ActionItemExtractor` (localized prompt, JSON schema, one retry)
- [x] Config keys `EXTRACT_ACTION_ITEMS`, `AZDO_*`, `GITHUB_*` (secrets masked) + `.env.example`
- [x] `TaskExporter` port, `AzureDevOpsExporter`, `GitHubIssuesExporter`, `TASK_EXPORTERS` registry
- [x] Stop step: extraction after minutes in `session.py` + `action_items_ready` event
- [x] API: `POST/GET/PUT /sessions/{id}/action-items`, `POST .../export`
- [x] UI: client methods + DTOs, `ActionItemsViewModel`, "Action items" tab, resources
- [x] Docs (architecture, api-contract), acceptance criteria, full suites, PR

### Decisions and notes

- `TaskExporter.create(TaskDraft) -> str` (one item per call) replaces the planned
  `export(items, session_title) -> list[str]`: per-item results are needed for
  `{created, failed}`, and the localized body is built by the caller so exporters need no
  localizer. Architecture §4/§5 updated.
- Azure DevOps: the due date goes to `Microsoft.VSTS.Scheduling.DueDate` only when it is an ISO
  date; if the process' Task type rejects it (HTTP 400) the task is created again without it (the
  due date is also in the description).
- Stop step: one line in `RecordingSession.stop()` after `_write_minutes()` plus
  `_extract_action_items()`; it runs only when minutes are on (`GENERATE_MINUTES`) and
  `EXTRACT_ACTION_ITEMS` is true, so the `WHISPER_KEEP_LOADED` keep rule is unchanged. New
  observer method `on_action_items_ready(session_id, count)` (console, WebSocket, fakes).
- API additions beyond the contract rows: `PUT /sessions/{id}/action-items` saves the UI edits
  (exported items stay as exported) and `GET` also returns `targets` (configured targets only),
  so the UI can offer the selector. `api-contract.md` updated.
- UI: self-contained `ActionItemsViewModel` (lazy `SessionDetailViewModel.ActionItems`, loaded
  with the detail when the session is not live) and `Views/ActionItemsPanel.axaml` in a new tab.
  Export first `PUT`s the edits of every editable row, then exports the selected ones. The task
  settings live in a new settings group `tasks` (`SettingsGroup_tasks`).

### Manual check recipe

Not run in the parallel session (no Ollama/GPU use, no tracker credentials).

1. **Extraction (Ollama `qwen2.5:7b`, existing session)** — start Ollama, then from `engine/`:
   `../.venv/Scripts/python -m vozata serve`. In another terminal:
   - `curl.exe -s "http://127.0.0.1:8765/sessions?limit=5"` → pick a `done` session `<id>` with a
     transcript that mentions tasks ("Ana will send the report by Friday").
   - `curl.exe -s -X POST http://127.0.0.1:8765/sessions/<id>/action-items` → `202`. Wait for the
     engine log / WebSocket `action_items_ready {session_id, count}` (about 10–60 s).
   - `curl.exe -s http://127.0.0.1:8765/sessions/<id>/action-items` → items with a short imperative
     `description` in `APP_LANGUAGE`, `owner` / `due` when said (due as `YYYY-MM-DD` relative to the
     meeting date), `source_segment_ids` that exist in the transcript, `targets: []` without
     credentials. `recordings/<id>/action_items.json` holds the same items.
   - `nvidia-smi` after the job: the Ollama model is unloaded (`OLLAMA_KEEP_ALIVE=0`).
2. **Stop step** — record a 1-minute session in the desktop app saying two tasks with owners and a
   date, stop it: after `minutes.md`, the session's "Action items" tab lists them (and the console
   of `python -m vozata record` prints "Action items extracted: N.").
3. **UI** — in the "Action items" tab edit a description, owner and due, press "Extract again"
   (items reload; exported ones stay), switch the app language (tab texts follow).
4. **Export — pending manual (credentials)**:
   - Azure DevOps: in Settings → Task export set `AZDO_ORG_URL` (`https://dev.azure.com/<org>`),
     `AZDO_PROJECT` (a test project) and `AZDO_PAT` (Work Items read & write); the PAT shows as
     `********` in `GET /settings`. Select one item, "Export to: Azure DevOps", "Export selected"
     → the row shows the work-item link and becomes read-only; open it: a Task with the title,
     description (meeting, time, owner, due, session folder), due date when ISO (if the process
     rejects `Microsoft.VSTS.Scheduling.DueDate`, the task is still created without it).
   - GitHub: set `GITHUB_REPO` (`<owner>/<test-repo>`) and `GITHUB_TOKEN` (Issues read & write);
     export another item → an issue with the same title/body opens from the link.
   - Re-export the same item: `curl.exe -s -X POST -H "Content-Type: application/json" -d
     "{\"target\":\"github\",\"item_ids\":[\"a1\"]}"
     http://127.0.0.1:8765/sessions/<id>/action-items/export` → `failed: [{item_id: "a1", error:
     "Already exported: …"}]`, nothing created. A wrong token gives a localized "rejected the
     credentials (HTTP 401)" under the item; the token never appears in the engine log.
