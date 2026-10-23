# Plan — Phase 54: suggest recording when a meeting app is in a call

Phase file: `docs/roadmap/phases/54-meeting-detection.md`. Branch `feature/54-meeting-detection`.

## Tasks

1. **Keys.** `MEETING_DETECTION` (bool, true), `MEETING_APPS` (string, comma-separated
   executables), `MEETING_POLL_SECONDS` (number, 5, 1–60) in `config.py` and `settings_fields.py`
   (group `general`); `.env.example`.
2. **Detector (`vozata/meeting/detector.py`).** Port `AudioSessionMonitor` in `ports.py`
   (`active_apps() -> set[str]`). `MeetingDetector(monitor, settings, recording, publish, clock)`:
   `poll()` reads the current settings each time (switch and list apply at once); a known app
   active for 2 polls in a row while nothing records → `publish(app, name)` once; suppressed
   again until that app was quiet for 60 s; a recording marks the apps active during it as
   suggested (no suggestion right after Stop in the same call). Display names for the known
   executables (`ms-teams.exe` → "Microsoft Teams", …), else the file name without `.exe`.
   `start()` / `stop()`: a daemon thread polling every `MEETING_POLL_SECONDS`.
3. **Windows monitor (`audio/sessions.py`).** `pycaw` (+ `comtypes`): every active render and
   capture endpoint's session manager, sessions in state Active, their process names; COM
   initialized on the polling thread; any COM error → empty set (logged once). Thin, covered by
   the manual check. New dependency `pycaw; sys_platform == 'win32'`.
4. **Wiring.** `bootstrap` builds the detector (Windows monitor, `manager.current is not None`
   as "recording", `broadcaster.publish("meeting_detected", None, {app, name})`), the container
   holds it, the API lifespan starts / stops it. api-contract `meeting_detected`.
5. **UI.** `MeetingDetectedEvent` in the client; `MeetingSuggestionViewModel` (Name, IsOpen,
   Record → the recorder's Start, Not now → close; a new event replaces the shown one; closed
   when a recording starts); a banner in `ShellView` under the recovery one; an in-app toast; RESX
   en / pt-BR / es (`MeetingDetected`, `MeetingRecord`, `MeetingNotNow`, the three setting labels).
6. **Docs, packaging.** `engine.spec` hidden imports `pycaw`, `comtypes`; architecture §9 keys;
   user guide section; phase notes.
7. **Checks.** Full suites; manual: the real Windows monitor lists the apps with active audio
   (Teams idle → nothing; a sound playing in a known app → listed); a scratch engine with a
   short poll and `MEETING_APPS` set to an app that plays audio (e.g. the media player) publishes
   `meeting_detected` over the WebSocket, once; nothing while a recording runs.
