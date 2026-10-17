using System.Diagnostics.CodeAnalysis;
using Avalonia.Controls;

namespace VozAta.Desktop.Diagnostics;

/// <summary>Every design token and style in light and dark side by side (debug builds only).</summary>
[ExcludeFromCodeCoverage(Justification = "Debug-only design review window.")]
public partial class ThemeGalleryWindow : Window
{
    public ThemeGalleryWindow()
    {
        InitializeComponent();
    }
}
