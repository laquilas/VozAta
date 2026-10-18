using System.Diagnostics.CodeAnalysis;
using Avalonia.Controls;

namespace VozAta.Desktop.Diagnostics;

[ExcludeFromCodeCoverage(Justification = "Debug-only design review view.")]
public partial class ThemeGalleryPanel : UserControl
{
    public ThemeGalleryPanel()
    {
        InitializeComponent();
    }
}
