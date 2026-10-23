using System.Diagnostics.CodeAnalysis;
using Avalonia;

namespace VozAta.Worker;

[ExcludeFromCodeCoverage(Justification = "Avalonia entry point.")]
internal sealed class Program
{
    [STAThread]
    public static void Main(string[] args) => BuildAvaloniaApp().StartWithClassicDesktopLifetime(args);

    public static AppBuilder BuildAvaloniaApp() =>
        AppBuilder.Configure<App>().UsePlatformDetect().WithInterFont().LogToTrace();
}
