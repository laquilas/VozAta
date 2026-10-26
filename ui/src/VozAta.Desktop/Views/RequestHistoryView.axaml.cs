using System.Diagnostics.CodeAnalysis;
using Avalonia.Controls;

namespace VozAta.Desktop.Views;

/// <summary>A meeting's request history (phase 59); bound to a <c>RequestHistoryViewModel</c>.</summary>
[ExcludeFromCodeCoverage(Justification = "View; covered by the manual check.")]
public partial class RequestHistoryView : UserControl
{
    public RequestHistoryView()
    {
        InitializeComponent();
    }
}
