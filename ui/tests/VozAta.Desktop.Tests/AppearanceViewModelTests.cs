using VozAta.Desktop.Services;
using VozAta.Desktop.Tests.Fakes;
using VozAta.Desktop.ViewModels;

namespace VozAta.Desktop.Tests;

public sealed class AppearanceViewModelTests
{
    private readonly FakePreferences _preferences = new();
    private readonly FakeThemeService _theme = new();
    private readonly LocalizationService _localization = new();

    private AppearanceViewModel Create() => new(_preferences, _theme, _localization);

    [Fact]
    public void The_saved_theme_is_selected_and_applied_at_start()
    {
        _preferences.Data = new UiPreferencesData(Theme: "dark");

        var appearance = Create();

        Assert.Equal("dark", appearance.SelectedTheme.Value);
        Assert.Equal(["dark"], _theme.Applied);
        Assert.Equal(0, _preferences.Saves);
    }

    [Fact]
    public void Without_a_saved_theme_the_system_theme_is_used()
    {
        var appearance = Create();

        Assert.Equal("system", appearance.SelectedTheme.Value);
        Assert.Equal(["system"], _theme.Applied);
    }

    [Theory]
    [InlineData("purple")]
    [InlineData("")]
    public void An_unknown_saved_theme_falls_back_to_the_system_theme(string saved)
    {
        _preferences.Data = new UiPreferencesData(Theme: saved);

        var appearance = Create();

        Assert.Equal("system", appearance.SelectedTheme.Value);
        Assert.Equal(["system"], _theme.Applied);
    }

    [Fact]
    public void Choosing_a_theme_applies_it_at_once_and_saves_it()
    {
        _preferences.Data = new UiPreferencesData(MinimizeToTray: true);
        var appearance = Create();

        appearance.SelectedTheme = appearance.Themes.Single(option => option.Value == "light");

        Assert.Equal(["system", "light"], _theme.Applied);
        Assert.Equal("light", _preferences.Data.Theme);
        Assert.True(_preferences.Data.MinimizeToTray); // other preferences are kept
    }

    [Fact]
    public void A_null_selection_from_the_view_is_ignored()
    {
        var appearance = Create();

        appearance.SelectedTheme = null!;

        Assert.Equal("system", appearance.SelectedTheme.Value);
        Assert.Equal(["system"], _theme.Applied);
        Assert.Equal(0, _preferences.Saves);
    }

    [Fact]
    public void The_choices_are_system_light_and_dark_with_localized_labels()
    {
        var appearance = Create();

        Assert.Equal(["system", "light", "dark"], appearance.Themes.Select(option => option.Value));
        Assert.Equal(["Use the system setting", "Light", "Dark"], appearance.Themes.Select(option => option.Label));

        _localization.SetLanguage("pt-BR");
        appearance.RefreshTexts();

        Assert.Equal(["Seguir o sistema", "Claro", "Escuro"], appearance.Themes.Select(option => option.Label));
    }

    [Fact]
    public void The_main_window_relabels_the_theme_choices_when_the_language_changes()
    {
        var main = new MainViewModel(
            new FakeEngineClient(), new FakeEngineEvents(), new FakeEngineProcess(), new ImmediateDispatcher(), _localization,
            new FakeDialogs(), _preferences, new FakeClock(), new FakeTimer(), new FakeShell(), new FakeFileSaver(), _theme);

        _localization.SetLanguage("es");

        Assert.Equal("Oscuro", main.Appearance.Themes.Single(option => option.Value == "dark").Label);
        Assert.Equal(["system"], _theme.Applied);
    }
}
