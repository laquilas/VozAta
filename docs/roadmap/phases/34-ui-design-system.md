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

- [ ] No hex color literal or raw `FontSize` number left in `Views/*.axaml` (a test greps the
      XAML files).
- [ ] Theme preference saved and restored; switching applies without restart (ViewModel test).
- [ ] Manual: every screen checked in light and dark mode (screenshots in the PR); contrast of
      text on sidebar and accent buttons ≥ 4.5:1.
- [ ] Resource parity test passes.

## Tests

`ThemeTokensTests.cs` (XAML grep), `UiPreferencesTests.cs` (theme), `SettingsViewModelTests.cs`.

## Out of scope

Layout changes (35–38), custom fonts beyond Inter.

## Kickoff prompt

> Execute phase 34 of the roadmap (`docs/roadmap/phases/34-ui-design-system.md`), following
> `docs/roadmap/README.md`.

## Progress

- **Branch:** `feature/34-ui-design-system`
- **Status:** in progress
- **Updated:** 2026-10-17 10:00
- **Next step:** headless render test (`Avalonia.Headless` in the test project) that loads every view in
  light and dark and can save screenshots.

### Steps

- [x] Tokens, icons (with license) and control styles merged in `App.axaml` — this commit
- [x] Theme preference (`ui.json` `theme`), `IThemeService`, picker in Settings → Desktop app — this commit
- [x] Views use tokens, styles and icons only (no hex / raw `FontSize`), `ThemeTokensTests` — this commit
- [x] Contrast test for the token pairs (≥ 4.5:1 in light and dark) — this commit
- [ ] `ThemeGalleryWindow` (debug builds only) and light/dark screenshots
- [ ] Docs (architecture), acceptance criteria, full UI suite, PR

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
