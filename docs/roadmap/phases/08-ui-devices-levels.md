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

- [ ] ViewModel tests: default selection, persisted selection restored, missing device fallback,
      dB mapping and decay, no-signal flag timing, ids sent on start.
- [ ] Manual: meters move with speech and with media playback; changing devices records from them.
- [ ] Resource parity test passes.

## Tests

`DevicesViewModelTests.cs`, `LevelMeterViewModelTests.cs`, `UiPreferencesTests.cs`.

## Out of scope

Mic test without a session, engine-side device changes during recording.

## Kickoff prompt

> Execute phase 08 of the roadmap (`docs/roadmap/phases/08-ui-devices-levels.md`), following
> `docs/roadmap/README.md`.

## Progress

- **Branch:** `feature/08-ui-devices-levels`
- **Status:** in progress
- **Updated:** 2026-10-16 13:00
- **Next step:** `ViewModels/DevicesViewModel.cs` (load `GET /devices`, restore by name then id, engine defaults, refresh, persist on change, `IsEnabled`) with `DevicesViewModelTests.cs`; `FakeEngineClient` gets scriptable devices

### Steps

- [x] Start the phase (README status, Progress section)
- [x] `IUiPreferences` + JSON file store — `4e579a7`
- [x] `IClock` / `IUiTimer` + `LevelMeterViewModel` (dB mapping, decay, peak-hold, no-signal) — this commit
- [ ] `DevicesViewModel` (load, defaults, restore by name, fallback, refresh, persist)
- [ ] `MainViewModel` + `MainWindow`: device pickers, meters, ids on start, window size; resources
- [ ] Manual: meters move with speech and media; changing devices records from them; criteria

### Decisions and notes

- WASAPI device ids are PortAudio indices that change when devices are plugged in or out, so the
  preferences keep the device **name and id**: the selection is restored by name first, then by id,
  else the engine's default.
- Meters rise instantly to a new reading and fall at a fixed rate on timer ticks; the peak marker
  holds for 1 s, then falls. The engine floors silence at −90 dBFS; the meter clamps −60…0 dB.
- The UI has no clock/timer abstraction yet: `IClock` (time now) and `IUiTimer` (periodic tick on
  the UI thread, Avalonia `DispatcherTimer`) are added so tests drive the meters by hand.
