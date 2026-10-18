using System.Diagnostics.CodeAnalysis;
using Avalonia.Controls;

namespace VozAta.Desktop.Views;

/// <summary>The player bar of a session page (phase 37); bound to a <c>PlayerBarViewModel</c>.</summary>
[ExcludeFromCodeCoverage(Justification = "View; covered by the manual check.")]
public partial class PlayerBar : UserControl
{
    public PlayerBar()
    {
        InitializeComponent();
    }
}
