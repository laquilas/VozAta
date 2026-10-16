# Phase 08 — UI devices and level meters

## Goal

Let the user choose the microphone and the system output (loopback) and see live level meters per
channel while recording.

## Depends on

07

## Read first

- `ui/CLAUDE.md`
- [api-contract.md](../api-contract.md) — `GET /devices`, `POST /sessions` device ids, `level` event

## Scope

| Item | Content |
|------|---------|
| `ViewModels/DevicesViewModel.cs` | loads `GET /devices`; `SelectedMic`, `SelectedLoopback` (defaults from the engine); refresh command; remembers the selection |
| `Services/UiPreferences.cs` | `IUiPreferences` persisted to `%APPDATA%/VozAta/ui.json` (device ids, window size); missing devices fall back to defaults |
| `ViewModels/LevelMeterViewModel.cs` | maps `rms_db` (−60…0 dB) to 0…1 with peak-hold and decay; "no signal" flag when the system channel stays below −60 dB for 30 s while recording |
| `Views/` | device ComboBoxes (disabled while recording) and two horizontal meters labelled with the localized speaker labels |
| `MainViewModel` | passes the selected device ids to `POST /sessions` |
| Resources | new keys in the three `.resx` files |

## Design notes

- Meter smoothing runs on a timer through `IClock`/`IUiDispatcher` so tests can drive it.
- The "no signal" hint tells the user to check the default output device / headphones.

## Acceptance criteria

- [x] ViewModel tests: default selection, persisted selection restored, missing device fallback,
      dB mapping and decay, no-signal flag timing, ids sent on start.
- [x] Manual: meters move with speech and with media playback; changing devices records from them.
- [x] Resource parity test passes.

## Tests

`DevicesViewModelTests.cs`, `LevelMeterViewModelTests.cs`, `UiPreferencesTests.cs`.

## Out of scope

Mic test without a session, engine-side device changes during recording.

## Kickoff prompt

> Execute phase 08 of the roadmap (`docs/roadmap/phases/08-ui-devices-levels.md`), following
> `docs/roadmap/README.md`.

## Progress

- **Branch:** `feature/08-ui-devices-levels`
- **Status:** ready for PR
- **Updated:** 2026-10-16 14:40
- **Next step:** open the PR (combined draft in `__pr__/feature-08-ui-devices-levels/`)

### Steps

- [x] Start the phase (README status, Progress section)
- [x] `IUiPreferences` + JSON file store — `4e579a7`
- [x] `IClock` / `IUiTimer` + `LevelMeterViewModel` (dB mapping, decay, peak-hold, no-signal) — `71633f5`
- [x] `DevicesViewModel` (load, defaults, restore by name, fallback, refresh, persist) — `b66dbd6`
- [x] `MainViewModel` + `MainWindow`: device pickers, meters, ids on start, window size; resources — `3ee9bef`
- [x] Manual: meters move with speech and media; changing devices records from them; criteria — this commit

### Decisions and notes

- WASAPI device ids are PortAudio indices that change when devices are plugged in or out, so the
  preferences keep the device **name and id**: the selection is restored by name first, then by id,
  else the engine's default.
- Meters rise instantly to a new reading and fall at a fixed rate on timer ticks; the peak marker
  holds for 1 s, then falls. The engine floors silence at −90 dBFS; the meter clamps −60…0 dB.
- The UI has no clock/timer abstraction yet: `IClock` (time now) and `IUiTimer` (periodic tick on
  the UI thread, Avalonia `DispatcherTimer`) are added so tests drive the meters by hand.
- **Manual check (2026-10-16, desktop app driven through Windows UI Automation).** The app
  started its engine and selected the engine defaults (JBL mic 15, JBL loopback 17 = the Windows
  default output). Recording while the phase 05 TTS meeting played: the system meter moved
  (level 0.4–0.6, peak up to 0.68) and fell back between sentences; the pickers were disabled while
  recording. Switching the loopback to the Realtek output (silent, playback stayed on the JBL)
  and recording 41 s: the system meter stayed at 0, no transcript lines, the "No sound from the
  system audio for 30 s" hint appeared, and `session.json` recorded
  `system: "Alto-falantes (2- Realtek(R) Audio) [Loopback]"`. After closing and relaunching, the
  Realtek loopback and the saved window size (1100×750) were restored. The test preferences file
  was deleted afterwards so the next real recording uses the defaults again.
- Not exercised by the check: the **mic meter** with real speech (nobody spoke into the mic during
  the run; it stayed at 0 as expected for silence) — covered by the view-model tests.
- Seen during the check: UI Automation exposes the selected device as the record's `ToString()`
  (`AudioDevice { Id = …, Name = … }`) while the dropdown items use the name; a screen reader
  would read the long form. Possible follow-up: an `AutomationProperties.Name` or a `ToString()`
  that returns the name.
