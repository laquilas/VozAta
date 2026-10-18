using CommunityToolkit.Mvvm.ComponentModel;
using VozAta.Desktop.Services;

namespace VozAta.Desktop.ViewModels;

/// <summary>
/// The theme picker of Settings → Desktop app (phase 34): system, light or dark, applied at once and
/// remembered in <c>ui.json</c>.
/// </summary>
public sealed partial class AppearanceViewModel : ObservableObject
{
    public const string SystemTheme = "system";

    private readonly IUiPreferences _preferences;
    private readonly IThemeService _theme;
    private readonly ILocalizationService _localization;

    public AppearanceViewModel(IUiPreferences preferences, IThemeService theme, ILocalizationService localization)
    {
        _preferences = preferences;
        _theme = theme;
        _localization = localization;
        Themes = [new(SystemTheme, "ThemeSystem"), new("light", "ThemeLight"), new("dark", "ThemeDark")];
        var saved = preferences.Load().Theme;
        _selectedTheme = Themes.FirstOrDefault(option => option.Value == saved) ?? Themes[0];
        theme.Apply(_selectedTheme.Value);
        RefreshTexts();
    }

    public IReadOnlyList<ChoiceOption> Themes { get; }

    private ChoiceOption _selectedTheme;

    /// <summary>The chosen theme; setting it applies and saves it (a null from the view is ignored).</summary>
    public ChoiceOption SelectedTheme
    {
        get => _selectedTheme;
        set
        {
            if (value is not null && SetProperty(ref _selectedTheme, value))
            {
                _theme.Apply(value.Value);
                _preferences.Save(_preferences.Load() with { Theme = value.Value });
            }
        }
    }

    public void RefreshTexts()
    {
        foreach (var option in Themes)
        {
            option.Refresh(_localization);
        }
    }
}
