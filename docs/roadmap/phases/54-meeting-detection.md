# Phase 54 — Suggest recording when a meeting app is in a call

## Goal

When Teams, Zoom, Webex, Slack or Discord starts using the microphone or plays call audio and
VozAta is not recording, VozAta shows a notification "Teams is in a call — record it?" with a
**Record** button. It never starts recording by itself: recording consent stays with the user.
From the backlog ("Auto-detect meeting apps").

## Depends on

11, 35

## Read first

- `engine/CLAUDE.md`, `ui/CLAUDE.md`
- `audio/devices.py`, `audio/capture.py` (`PortAudioThread`), `api/events.py`, the session
  manager (is a recording running?), `settings_fields.py`
- UI: the tray / notification service of phase 11, `ShellViewModel.cs` (start a recording),
  `Strings*.resx`

## Scope

**Engine**

- Port `AudioSessionMonitor` (`active_apps() -> set[str]`: the executables with an active
  Windows audio session, render or capture). Windows provider through `pycaw` (COM
  `IAudioSessionManager2`), a fake for tests.
- `meeting/detector.py`: polls every `MEETING_POLL_SECONDS` (5); a known app (`MEETING_APPS`,
  default `ms-teams.exe, Teams.exe, Zoom.exe, CiscoCollabHost.exe, webex.exe, slack.exe,
  Discord.exe`) active for two polls in a row while no session records → one
  `meeting_detected {app, name}` event; again only after that app was quiet for a minute or
  after a recording of it ended. Nothing while recording or paused.
- Keys: `MEETING_DETECTION` (bool, default true), `MEETING_APPS`, `MEETING_POLL_SECONDS`.
- Browser calls (Meet in Chrome / Edge) are not detected: a browser playing audio is not a call.

**UI**: a toast (and a tray balloon when the window is hidden) "{name} is in a call. Record it?"
with **Record** (starts a recording with the current devices) and **Not now**; texts in
en / pt-BR / es; a Config switch for `MEETING_DETECTION`.

**Packaging / docs**: `pycaw` (and `comtypes`) in the engine bundle; api-contract
(`meeting_detected`), architecture §9 keys, `docs/USER_GUIDE` section.

## Acceptance criteria

- [ ] Joining a Teams or Zoom call with VozAta idle shows the suggestion within ~10 s; Record
      starts a recording; nothing appears while recording.
- [ ] With `MEETING_DETECTION=false` nothing is polled.

## Tests

Detector with a fake monitor and clock (debounce, quiet period, recording suppresses,
unknown apps, case-insensitive names), event payload, settings; UI toast view model (Record
starts a session, Not now dismisses), resource parity.

## Out of scope

Detecting browser calls, auto-start, auto-stop when the call ends, macOS / Linux.

## Kickoff prompt

> Start phase 54 (`docs/roadmap/phases/54-meeting-detection.md`): read its *Read first* files,
> write `plans/54-meeting-detection.md`, then implement it task by task.
