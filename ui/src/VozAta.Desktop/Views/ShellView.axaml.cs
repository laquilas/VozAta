using System.Diagnostics.CodeAnalysis;
using Avalonia.Controls;

namespace VozAta.Desktop.Views;

[ExcludeFromCodeCoverage(Justification = "View; logic lives in ShellViewModel.")]
public partial class ShellView : UserControl
{
    public ShellView()
    {
        InitializeComponent();
    }
}
