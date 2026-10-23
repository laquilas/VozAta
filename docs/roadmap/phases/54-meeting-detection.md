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

**UI**: a banner on top of the window (like the recovery offer) and an in-app toast "{name} is in a
call. Record it?" with **Record** (starts a recording with the current devices) and **Not now**;
texts in en / pt-BR / es; a Config switch for `MEETING_DETECTION`. The app has no Windows
notifications yet, so nothing shows while it sits in the tray (out of scope).

**Packaging / docs**: `pycaw` (and `comtypes`) in the engine bundle; api-contract
(`meeting_detected`), architecture §9 keys, `docs/USER_GUIDE` section.

## Acceptance criteria

- [x] Joining a Teams or Zoom call with VozAta idle shows the suggestion within ~10 s; Record
      starts a recording; nothing appears while recording.
- [x] With `MEETING_DETECTION=false` nothing is polled.

## Tests

Detector with a fake monitor and clock (debounce, quiet period, recording suppresses,
unknown apps, case-insensitive names), event payload, settings; UI toast view model (Record
starts a session, Not now dismisses), resource parity.

## Out of scope

Detecting browser calls, auto-start, auto-stop when the call ends, Windows toast notifications,
macOS / Linux.

## Kickoff prompt

> Start phase 54 (`docs/roadmap/phases/54-meeting-detection.md`): read its *Read first* files,
> write `plans/54-meeting-detection.md`, then implement it task by task.

## Progress

- **Branch:** `feature/54-meeting-detection`
- **Status:** ready for PR
- **Updated:** 2026-10-23
- **Next step:** open the PR to `main`; then phase 55 (`docs/roadmap/phases/55-wer-benchmark.md`).

### Steps

- [x] Implementation plan (`plans/54-meeting-detection.md`)
- [x] Keys `MEETING_DETECTION`, `MEETING_APPS`, `MEETING_POLL_SECONDS`
- [x] Detector (port, debounce, quiet period, recording suppresses)
- [x] Windows audio session monitor (pycaw)
- [x] Wiring: bootstrap, container, lifespan, `meeting_detected` event
- [x] UI: event, suggestion banner, texts
- [x] Docs and packaging
- [x] Full suites, manual check, phase done

### Decisions and notes

- Commits stay local until the PR (user rule, 2026-10-20).
- Teams running idle keeps its audio sessions *inactive* (checked on this PC with pycaw), so an
  active session of a known app is the call signal; two polls in a row skip notification sounds.
- `MEETING_APPS` stays the raw text in `Settings` (the Config page edits it as text); the detector
  splits it.
- Smoke run of `WindowsAudioSessions` on this PC: 0.12 s per poll; idle it lists only
  `QuantumServer.exe` (the JBL headset software keeps a session), a WAV played through `SoundPlayer`
  adds `powershell.exe`, also when called from another thread (COM initialized per thread).
- Tests never read the real audio sessions: an autouse fixture in `tests/conftest.py` stubs
  `WindowsAudioSessions.active_apps`.
- The suggestion is a banner only (no extra toast: it already carries the buttons); it opens only
  while the recorder is idle and closes on a `recording` / `paused` status.
- Manual check (2026-10-23): a scratch engine (own folder, `.env`, port) with
  `MEETING_APPS=powershell.exe` and a 1 s poll: a WAV played through `SoundPlayer` (a powershell.exe
  audio session) gave exactly one `meeting_detected {powershell.exe, Powershell}` on the WebSocket;
  during a recording (`POST /sessions`, audio only) and right after Stop in the same "call" none;
  the test meeting was deleted. `MEETING_DETECTION=false` is covered by the detector tests (nothing
  is even polled). Engine 2590 tests (99.4 %), UI 923 + 25, ruff / dotnet format clean. Not checked:
  a real Teams / Zoom call, the banner in the running app, the installed build.
