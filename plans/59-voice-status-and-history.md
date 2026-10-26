# Phase 59 — Voice command status in the menu + per-meeting request history

## Context

When the user says "VozAta, gere a ata" while recording, the app only shows a short "Ouvi: …"
toast and an indeterminate bar on the Recorder page. Nothing in the menu says whether the command
was understood, is being processed, finished or failed, so people repeat it, and a repeat within
15 s is dropped silently (`commands/detector.py` cooldown, only logged). Outcome:

- a status icon + text in the sidebar menu, only while recording, coloured: **gray** idle,
  **green** recognized / done, **yellow** processing, **red** failed;
- e.g. "Gerar a ata" (green) → "Gerando a ata…" (yellow) → "Ata pronta (até 12:34)" (green, 5 s)
  → gray; same for voice questions ("O que decidimos?" → "Respondendo…" → "Resposta pronta");
- the voice-made minutes go to **Atas parciais** covering the meeting up to the second of the
  request (today: up to the last transcribed segment, which includes the command itself);
- a repeat within the cooldown shows yellow "Já estou gerando a ata" instead of nothing;
- a short sound when a command is recognized (Config switch);
- clicking the green "Ata pronta" / "Resposta pronta" opens the result on the Recorder page;
- a **request history per meeting** (voice commands and requests for partial / range minutes,
  minutes again, action items, questions), shown only in that meeting.

Branch `feature/59-voice-status-and-history`, plan copy in `plans/59-voice-status-and-history.md`,
the usual workflow: phase file + README row first, TDD, one concern per commit, local checks,
manual check on a scratch port, PR, merge.

## Engine

### 1. Request log (the history), one service for every request kind

- `domain.py`: `RequestEntry` (frozen): `id`, `created_at`, `at` (meeting second, `None` after the
  meeting), `kind` (`minutes_so_far` | `range_minutes` | `minutes` | `action_items` | `ask`),
  `source` (`voice` | `button` | `range` | `app`), `text` (the heard phrase / the question / ""),
  `status` (`recognized` | `running` | `done` | `failed` | `ignored`), `result_id` (partial_id /
  answer_id / None), `message` (error code or None), `finished_at`; `to_dict` / `from_dict` like
  `PartialMinutes` (`domain.py:339-372`).
- Storage, mirroring partial minutes exactly:
  - port methods `read_requests(session_id)` / `write_requests(session_id, items)` in `ports.py`
    next to the partial-minutes ones (`ports.py:463-467`);
  - files backend `storage/requests.py` → `requests.json` (copy of `storage/partial_minutes.py`,
    `layout.py` gets `requests_json`);
  - SQLite: new migration `storage/sqlite/migrations/NNN_requests.sql` (table `requests`, keyed
    by session, `row_id` order) and methods in `storage/sqlite/annotations.py` like
    `read/write_partial_minutes` (:144-160);
  - include it wherever partial minutes are carried (bundle export/import of phase 39, session
    delete) — check `storage/bundle*`, `folder_reader.py` when implementing.
- `api/request_log.py`: `RequestLog(store, broadcaster, clock)` with `begin(session_id, kind,
  source, text, at, status="running") -> RequestEntry`, `update(session_id, id, status,
  result_id=None, message=None)`; appends under a lock, persists, publishes
  **`request_updated {request: RequestEntry}`** (envelope `session_id`). Capped at 200 entries
  per meeting.
- Hooks (each a small call, no orchestrator rewrite):
  - `api/voice_dispatch.py`: on a command → `begin(..., source="voice", status="recognized")`,
    then `update(running)` when the job starts, `update(failed, message="voice_command_busy")`
    when busy;
  - `api/partial_minutes_job.py`: gets an optional `request_id`; on success `update(done,
    result_id=partial_id)`, on failure `update(failed, message=code)`; `routes/partial_minutes.py`
    begins an entry for button / range requests;
  - `routes/ask.py` with a `session_id` and voice asks: `begin(kind="ask")`, `AskJob` finishes it on
    `answer_done` / failure;
  - `routes/sessions.py` regenerate minutes and `routes/action_items.py` extract: `begin`, and the
    queue job's existing completion (`minutes_ready` / `action_items_ready` / its failure path)
    finishes it — find the publish points in the processing queue when implementing.
- `GET /sessions/{id}/requests` → `{items: [RequestEntry]}` (new `routes/requests.py`).

### 2. Voice commands: the exact second, and repeats

- `commands/detector.py`: pass the command segment's `start` (meeting seconds) to the dispatch
  callback; on a repeat inside `COOLDOWN_SECONDS` call a new `on_repeat(action, phrase, at)`
  instead of only logging.
- `api/voice_dispatch.py`: minutes → `PartialRequest(session_id, 0.0, at, "voice", True)` (end =
  the second "VozAta" was said, so the command line and later talk are left out); repeat →
  `request_updated` entry with `status="ignored"`, `message="voice_command_repeated"` plus the
  existing `voice_command` event gets `request_id` and `at`.
- Check `minutes/partial_minutes.py:37-93` keeps the live wording (`minutes.scope_live`) with a
  given end, and records that end.
- `docs/roadmap/api-contract.md`: `request_updated`, `GET /sessions/{id}/requests`, the new
  `voice_command` fields; `architecture.md`: the request log; locales for new error codes in
  en / pt-BR / es.

## UI (Avalonia)

### 3. Voice status in the sidebar

- `VozAta.Client`: `RequestEntry` record, `RequestUpdatedEvent` parsed in `EngineEvents.cs` (like
  `VoiceCommandEvent` :89-94), `GetRequestsAsync` on `IEngineClient` + `EngineClient` + fake.
- `ViewModels/VoiceStatusViewModel.cs`: state `Idle | Recognized | Processing | Done | Failed`;
  visible only while `RecordingSessionService.IsRecording` and voice commands are on; follows
  `request_updated` entries with `source == "voice"` of the current session:
  `recognized` → green, action text ("Gerar a ata" / the question) for 1.5 s, then yellow
  "Gerando a ata…" / "Respondendo…" when `running`; `ignored` → yellow "Já estou gerando a ata";
  `done` → green "Ata pronta (até mm:ss)" / "Resposta pronta" for 5 s → gray; `failed` → red with
  the localized reason for 8 s → gray. Timers through an injected `IClock`/delay abstraction so
  tests run instantly. `OpenCommand` (enabled when done) opens the partial minutes / answer on the
  Recorder page (reuse `Recorder.MinutesSoFar` and `Recorder.VoiceAnswer` open paths).
- `Views/ShellView.axaml`: under the processing indicator (:92-105), same `Auto,*` grid pattern
  (PathIcon + text, text hidden when the sidebar is collapsed, tooltip with the full text); colours
  as theme brushes (`Brush.Status.Idle/Ok/Busy/Error`, light and dark).
- `MainViewModel.Handle` (:419-528): route `RequestUpdatedEvent` to `VoiceStatus`, `Recorder` and
  `History`; keep the "Ouvi" toast; `RefreshTexts` on language change.
- Sound: `Services/ISoundPlayer` + Windows `PlaySound` (winmm P/Invoke) implementation playing an
  embedded short WAV; played on a voice `recognized` entry when the UI setting
  `VoiceCommandSound` (ui.json, default on) is on; toggle on the Config voice-commands card.

### 4. Request history in the meeting

- `SessionPageViewModel`: new `Requests` list view model (pattern of `PartialMinutesListViewModel`,
  `PartialMinutesViewModels.cs:126-242`): `LoadAsync` via `GetRequestsAsync`, live updates from
  `request_updated` of that session; rows "12:34 · Comando de voz · Gerar a ata · Pronta" with a
  status dot of the same colours and a link to the partial minutes / answer when `result_id`.
- `Views/SessionPage.axaml`: a **Histórico** tab next to **Atas parciais** (:159); the Recorder page
  shows the same list for the meeting being recorded (small expander under the answer panel).
- Strings in `Strings.resx` / `.pt-BR` / `.es` (status texts, kinds, sources, tab, sound switch).

## Tests

- Engine: `RequestLog` (append, update, cap, events, persistence on both backends via the shared
  storage contract tests); detector `at` + `on_repeat`; dispatcher (recognized → running → done,
  busy, repeat ignored, end = command second); partial-minutes job finishing entries; routes
  (button/range/ask/regenerate/action-items begin entries; `GET /requests`); migration test.
- UI: `VoiceStatusViewModel` state machine with a fake clock (every transition, 5 s / 8 s back to
  gray, hidden when not recording, only voice entries, Open command), event parsing, `MainViewModel`
  routing, requests list (load, live update, other session ignored), sound played / not played,
  resource parity test (existing).
- Full local suites: engine `ruff check`, `ruff format --check`, `pytest` (≥ 80 % diff coverage);
  UI `dotnet build`, `dotnet test`, `dotnet format --verify-no-changes`.

## Manual verification (scratch port, never the real `.env`)

- Scratch engine (`API_PORT=8775`, scratch `OUTPUT_DIR` / `DATABASE_PATH`, `HF_HUB_OFFLINE=1`) +
  Debug app pointed at it; record and play a TTS clip "VozAta, gere a ata" through the speakers
  (technique in the reference-machine memory): the sidebar goes green → yellow → green "Ata pronta
  (até mm:ss)" 5 s → gray; the sound plays; a repeat within 15 s shows yellow "Já estou gerando";
  Ollama stopped → red. The partial minutes appear in Atas parciais with end = the command second;
  the Histórico tab lists the voice command and a button request. Screenshots via `PrintWindow`
  into the phase file.
