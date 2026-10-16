using System.ComponentModel;
using System.Globalization;
using System.Resources;

namespace VozAta.Desktop.Services;

/// <summary>User-facing strings from Resources/Strings*.resx, switchable at runtime.</summary>
public interface ILocalizationService : INotifyPropertyChanged
{
    /// <summary>Supported app languages, as the engine names them (`APP_LANGUAGE`).</summary>
    IReadOnlyList<string> Languages { get; }

    string Language { get; }

    /// <summary>The string for <paramref name="key"/> in the current language.</summary>
    string this[string key] { get; }

    string Format(string key, params object?[] args);

    /// <summary>Switch language; unknown values fall back to English. Bindings refresh.</summary>
    void SetLanguage(string language);
}

public sealed class LocalizationService : ILocalizationService
{
    public const string Default = "en";

    private static readonly ResourceManager Resources = new(
        "VozAta.Desktop.Resources.Strings", typeof(LocalizationService).Assembly);

    private CultureInfo _culture = CultureInfo.GetCultureInfo(Default);

    public event PropertyChangedEventHandler? PropertyChanged;

    public IReadOnlyList<string> Languages { get; } = [Default, "pt-BR", "es"];

    public string Language { get; private set; } = Default;

    public string this[string key] => Resources.GetString(key, _culture) ?? $"[{key}]";

    public string Format(string key, params object?[] args) =>
        string.Format(_culture, this[key], args);

    public void SetLanguage(string language)
    {
        Language = Languages.Contains(language) ? language : Default;
        _culture = CultureInfo.GetCultureInfo(Language);
        PropertyChanged?.Invoke(this, new PropertyChangedEventArgs(nameof(Language)));
        PropertyChanged?.Invoke(this, new PropertyChangedEventArgs("Item[]"));
    }
}
