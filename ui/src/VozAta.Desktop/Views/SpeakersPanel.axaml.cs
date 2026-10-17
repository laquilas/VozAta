using System.Diagnostics.CodeAnalysis;
using Avalonia.Controls;

namespace VozAta.Desktop.Views;

/// <summary>The "Speakers" tab of a session (phase 16); bound to a <c>SpeakersViewModel</c>.</summary>
[ExcludeFromCodeCoverage(Justification = "View; covered by the manual check.")]
public partial class SpeakersPanel : UserControl
{
    public SpeakersPanel()
    {
        InitializeComponent();
    }
}
