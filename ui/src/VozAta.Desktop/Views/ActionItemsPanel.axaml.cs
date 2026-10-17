using System.Diagnostics.CodeAnalysis;
using Avalonia.Controls;

namespace VozAta.Desktop.Views;

/// <summary>The "Action items" tab of a session (phase 23); bound to an <c>ActionItemsViewModel</c>.</summary>
[ExcludeFromCodeCoverage(Justification = "View; covered by the manual check.")]
public partial class ActionItemsPanel : UserControl
{
    public ActionItemsPanel()
    {
        InitializeComponent();
    }
}
