using System.Diagnostics.CodeAnalysis;
using Avalonia.Controls;

namespace VozAta.Worker;

[ExcludeFromCodeCoverage(Justification = "View.")]
public partial class WorkerWindow : Window
{
    public WorkerWindow() => InitializeComponent();
}
