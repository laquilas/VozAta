# Phase 34 — UI design system

## Goal

Give the desktop app a consistent look in the style of Toggl Track, in light and dark mode:
design tokens (colors, spacing, radii, type), an icon set and shared control styles. Only the look
changes, not the layout. Phases 35–38 build the new layout on top.

## Depends on

13

## Read first

- `ui/CLAUDE.md`
- `ui/src/VozAta.Desktop/App.axaml`, `Views/MainWindow.axaml`, `Views/HistoryView.axaml`,
  `Views/SettingsView.axaml` (current hard-coded colors and styles)

## Scope

**UI**

| File | Content |
|------|---------|
| `Themes/Tokens.axaml` | `ThemeDictionaries` for `Light` and `Dark`: `Brush.Sidebar` (deep purple, e.g. `#2C1338`), `Brush.SidebarText`, `Brush.Accent` (pink/magenta, e.g. `#E57CD8`, used for the start button and selection), `Brush.Danger` (stop, errors), `Brush.Warning`, `Brush.Success`, `Brush.Surface`, `Brush.SurfaceAlt`, `Brush.Border`, `Brush.TextPrimary`, `Brush.TextSecondary`; spacing (`Space.1`…`Space.6`), radii (`Radius.Small/Medium/Pill`), type scale (`FontSize.Caption/Body/Title/Timer`) |
| `Themes/Icons.axaml` | `StreamGeometry` resources from Fluent UI System Icons (MIT; license file in `Assets/licenses/`): play, stop, pause, record, history, search, settings, chat, speaker, export, delete, folder, chevrons, sun/moon |
| `Themes/Controls.axaml` | styles with classes: `Button.primary`, `Button.round-start` (big circular accent button), `Button.round-stop`, `Button.ghost`, `Button.icon`, `Border.card`, `TextBlock.caption`, `TextBlock.timer`, `Border.tag` (pill tags for template/language), banner styles (info/warning/error) |
| `App.axaml` | merge the three dictionaries after `FluentTheme`; `RequestedThemeVariant` from preferences |
| Views | replace every hard-coded hex color, font size and margin with the tokens (e.g. `MainWindow.axaml` `Button.danger`, recovery banner, notifications, history badges) and every glyph button (`⟳`, `✕`) with icons |
| `Services/UiPreferences.cs` | `Theme: system\|light\|dark` in `ui.json`; Settings → Desktop app gets a theme picker (applies immediately) |
| Resources | strings for the theme picker in en / pt-BR / es |

## Design notes

- Accent pink on dark purple is the Toggl signature; keep the contrast ratio ≥ 4.5:1 for text
  (check both themes); if a pair fails, adjust the token, not the view.
- No new NuGet package needed (geometry icons). Inter stays the font; the timer uses a tabular
  number style (`FontFeatures="tnum"`) instead of Consolas.
- A small `ThemeGalleryWindow` (debug builds only) shows every token and style in both themes, to
  review the palette without running the engine.

## Acceptance criteria

- [x] No hex color literal or raw `FontSize` number left in `Views/*.axaml` (a test greps the
      XAML files).
- [x] Theme preference saved and restored; switching applies without restart (ViewModel test).
- [x] Manual: every screen checked in light and dark mode (screenshots in the PR); contrast of
      text on sidebar and accent buttons ≥ 4.5:1. *(Headless renders of every page in both themes
      reviewed; contrast automated in `ThemeContrastTests`; real-window check: recipe in Progress.)*
- [x] Resource parity test passes.

## Tests

`ThemeTokensTests.cs` (XAML grep), `UiPreferencesTests.cs` (theme), `SettingsViewModelTests.cs`.

## Out of scope

Layout changes (35–38), custom fonts beyond Inter.

## Kickoff prompt

> Execute phase 34 of the roadmap (`docs/roadmap/phases/34-ui-design-system.md`), following
> `docs/roadmap/README.md`.

## Progress

- **Branch:** `feature/34-ui-design-system`
- **Status:** ready for PR
- **Updated:** 2026-10-17 10:00
- **Next step:** attach the light/dark screenshots to PR #44, run the manual check recipe below, then merge.

### Steps

- [x] Tokens, icons (with license) and control styles merged in `App.axaml` — this commit
- [x] Theme preference (`ui.json` `theme`), `IThemeService`, picker in Settings → Desktop app — this commit
- [x] Views use tokens, styles and icons only (no hex / raw `FontSize`), `ThemeTokensTests` — this commit
- [x] Contrast test for the token pairs (≥ 4.5:1 in light and dark) — this commit
- [x] `ThemeGalleryWindow` (debug builds only) and light/dark screenshots — this commit
- [x] Docs (architecture), acceptance criteria, full UI suite — this commit
- [x] PR #44 opened, CI (lint, format, build) green

### Decisions and notes

- Runs in parallel with phase 30 (engine only): no shared files expected.
- Icons: Fluent UI System Icons, 20 px variants, path data copied into `Themes/Icons.axaml` (`F1`
  prefix keeps the SVG nonzero fill); MIT license in `Assets/licenses/`.
- Text on the pink accent is the dark purple `Brush.OnAccent` (white on `#E57CD8` is only 2.6:1).
  Status colors are split into fills (`Brush.Danger`), text on surfaces (`Brush.DangerText`) and
  banner backgrounds (`Brush.DangerSurface`) so each pair passes 4.5:1 in both themes.
- `FluentTheme` palettes use the same accent so Fluent controls (selection, toggles) match.
- Theme picker lives in `AppearanceViewModel` (`MainViewModel.Appearance`, next to `Tray`) instead of
  `SettingsViewModel`: it is a desktop-app preference like Minimize to tray, not an engine setting.
  Tests in `AppearanceViewModelTests.cs`. `IThemeService` / `AvaloniaThemeService` is wired in `App.axaml.cs`.
- Transcript colors: `TranscriptLine.Color` (hex strings in the ViewModel) became `IsMic` / `IsSystem`;
  views pick `Brush.Channel*` through the `channel` / `mic` / `system` classes, so dark mode gets
  lighter speaker colors. Faded text (`Opacity=0.6`) became `Brush.TextSecondary` (`secondary` /
  `hint` / `caption` classes) so its contrast is measurable. Small item margins stay numeric; page,
  card and banner insets use `Inset.*` tokens (layout unchanged).- `ThemeContrastTests` reads `Tokens.axaml` and checks 26 text/background pairs per theme; it caught
  `OnAccent` on the light `AccentPressed` (4.2:1), so the pressed accent is now lighter (`#EE9BE3`).
- `ThemeRenderTests` (new test dependency `Avalonia.Headless`, CPU Skia rendering, no window on screen)
  renders every page in light and dark with fake engine data; with `VOZATA_SCREENSHOTS=<folder>` it saves
  the PNGs used in the PR. Start goes to the fake engine only (no audio).
- `ThemeGalleryWindow` lives in `Diagnostics/` (excluded from non-Debug builds in the csproj) and opens with
  `dotnet run --project src/VozAta.Desktop -- --theme-gallery`: light and dark side by side through
  `ThemeVariantScope`, no engine started. `ThemeRenderTests` renders it too (Debug only).
- Full UI suite (Debug): 455 passed, 0 failed; `dotnet format --verify-no-changes` clean; Release build OK.

### Manual check recipe

No microphone, speaker or GPU is needed; do not start a recording.

1. Gallery: `cd ui` then `dotnet run --project src/VozAta.Desktop -- --theme-gallery`. Light (left) and
   dark (right) show every brush, text style, button, tag, banner and icon. Check: text readable on
   every swatch, pink buttons have dark purple text, red buttons white text, icons crisp.
2. Screenshots without the engine: `cd ui`, set `VOZATA_SCREENSHOTS` to an empty folder
   (PowerShell: `$env:VOZATA_SCREENSHOTS = "$env:TEMP\vozata-shots"`), run
   `dotnet test --filter FullyQualifiedName~ThemeRender`. The folder gets
   `recording-idle|recording-active|history-minutes|history-transcript|settings-{light,dark}.png` and
   `theme-gallery.png` (fake engine data; Start only reaches the fake engine).
3. Real window: `dotnet run --project src/VozAta.Desktop` (the engine starts but nothing records).
   Settings → Desktop app → Theme: pick Dark, then Light, then "Use the system setting": the whole
   window switches at once, no restart. Take a screenshot of each tab per theme (Win+Shift+S).
4. Close and reopen the app: the chosen theme is restored (`%APPDATA%\VozAta\ui.json` has
   `"theme": "dark"` or `"light"`). With "Use the system setting", switch Windows Settings →
   Personalization → Colors → Light/Dark: the app follows.
5. Switch the interface language to Português and Español: the theme picker labels are translated.
6. Optional (reference machine, one phase at a time): start a short recording and check the red Stop
   button, recording dot, timer digits (tabular, no jitter) and channel colors in both themes.