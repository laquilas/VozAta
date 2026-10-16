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
