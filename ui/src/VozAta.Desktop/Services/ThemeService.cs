using System.Diagnostics.CodeAnalysis;
using Avalonia;
using Avalonia.Styling;

namespace VozAta.Desktop.Services;

/// <summary>Switches the app between the light and dark design tokens (phase 34).</summary>
public interface IThemeService
{
    /// <summary>Apply <c>system</c>, <c>light</c> or <c>dark</c> at once; anything else follows the system.</summary>
    void Apply(string theme);

    /// <summary>Whether the app shows the dark tokens now (with <c>system</c>: what the system chose).</summary>
    bool IsDark { get; }
}

[ExcludeFromCodeCoverage(Justification = "Sets Avalonia's application theme; ViewModel tests use a fake.")]
public sealed class AvaloniaThemeService : IThemeService
{
    public bool IsDark => Application.Current?.ActualThemeVariant == ThemeVariant.Dark;

    public void Apply(string theme)
    {
        if (Application.Current is { } application)
        {
            application.RequestedThemeVariant = theme switch
            {
                "light" => ThemeVariant.Light,
                "dark" => ThemeVariant.Dark,
                _ => ThemeVariant.Default,
            };
        }
    }
}
