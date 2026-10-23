# Phase 59 — Voice command status in the menu; request history per meeting

## Goal

During a recording, a status icon with a line of text in the sidebar says what happened to a voice
command: **gray** idle, **green** recognized / done, **yellow** processing, **red** failed
("Gerar a ata" → "Gerando a ata…" → "Ata pronta (até 12:34)" for 5 s → gray; the same for voice
questions). Today only a short toast says "Ouvi: …", so people repeat the command, and a repeat
within the 15 s cooldown is dropped silently. Also:

- the minutes asked for by voice cover the meeting up to the second of the request;
- a repeat within the cooldown shows "Já estou gerando a ata";
- a short sound when a command is recognized (a Config switch);
- clicking the green result opens it on the Recorder page;
- a **request history** per meeting: voice commands and requests for minutes so far, minutes of a
  range, minutes again, action items and questions, with time and outcome.

## Depends on

48, 49, 50

## Read first

- `engine/CLAUDE.md`, `ui/CLAUDE.md`
- `commands/detector.py`, `api/voice_dispatch.py`, `api/partial_minutes_job.py`,
  `minutes/partial_minutes.py`, `storage/partial_minutes.py`, `storage/sqlite/annotations.py`
- `ui/.../ViewModels/MainViewModel.cs` (`Handle`), `ProcessingIndicatorViewModel.cs`,
  `PartialMinutesViewModels.cs`, `Views/ShellView.axaml`, `Views/SessionPage.axaml`
- `plans/59-voice-status-and-history.md` (the approved plan)

## Scope

See the plan. Engine: `RequestEntry` + storage on both backends + `RequestLog` publishing
`request_updated`, hooks in the voice dispatcher, partial minutes, ask, minutes again and action
items, `GET /sessions/{id}/requests`; the detector passes the command second and reports repeats.
UI: `VoiceStatusViewModel` in the sidebar, the sound, the Histórico tab and the Recorder list.

## Acceptance criteria

- [ ] While recording, "VozAta, gere a ata" turns the sidebar icon green "Gerar a ata", then
      yellow "Gerando a ata…", then green "Ata pronta (até mm:ss)" for 5 s, then gray.
- [ ] A voice question goes green → yellow "Respondendo…" → green "Resposta pronta" → gray.
- [ ] A failure is red with its reason; a repeat within 15 s shows yellow "Já estou gerando a ata".
- [ ] The voice minutes end at the second the command was said and show in Atas parciais.
- [ ] A short sound plays on a recognized command, unless switched off in Config.
- [ ] Clicking the green result opens it on the Recorder page.
- [ ] The meeting page has a Histórico tab with every request of that meeting.

## Tests

`RequestLog` and its storage on both backends, the hooks, the detector second and repeats, the
routes; the UI state machine with a fake clock, the routing, the history list, the sound switch.

## Out of scope

A global history across meetings; spoken (text-to-speech) answers.

## Kickoff prompt

> Start phase 59 (`docs/roadmap/phases/59-voice-status-and-history.md`): read its *Read first*
> files and `plans/59-voice-status-and-history.md`, then implement it task by task.

## Progress

- **Branch:** `feature/59-voice-status-and-history`
- **Status:** in progress
- **Updated:** 2026-10-23 19:40
- **Next step:** `RequestEntry` in `domain.py` and its storage (files + SQLite) with tests.

### Steps

- [x] Phase start (phase file, plan, README)
- [ ] Engine: `RequestEntry` + storage (files, SQLite migration, bundle)
- [ ] Engine: `RequestLog`, `request_updated`, `GET /sessions/{id}/requests`
- [ ] Engine: hooks (voice, partial minutes, ask, minutes again, action items)
- [ ] Engine: detector command second + repeats; voice minutes end at the command
- [ ] UI client: `RequestEntry`, `RequestUpdatedEvent`, `GetRequestsAsync`
- [ ] UI: `VoiceStatusViewModel` + sidebar + sound + Config switch
- [ ] UI: Histórico tab + Recorder list
- [ ] Docs (api-contract, architecture); suites; manual check; PR
