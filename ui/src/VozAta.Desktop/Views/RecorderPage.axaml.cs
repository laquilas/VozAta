using System.Diagnostics.CodeAnalysis;
using Avalonia.Controls;

namespace VozAta.Desktop.Views;

[ExcludeFromCodeCoverage(Justification = "View; logic lives in RecorderPageViewModel.")]
public partial class RecorderPage : UserControl
{
    public RecorderPage()
    {
        InitializeComponent();
    }
}
