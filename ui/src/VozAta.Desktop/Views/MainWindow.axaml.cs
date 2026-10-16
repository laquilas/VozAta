using System.Diagnostics.CodeAnalysis;
using Avalonia.Controls;

namespace VozAta.Desktop.Views;

[ExcludeFromCodeCoverage(Justification = "View; logic lives in MainViewModel.")]
public partial class MainWindow : Window
{
    public MainWindow()
    {
        InitializeComponent();
    }
}
