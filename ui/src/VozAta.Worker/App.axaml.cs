using System.Diagnostics.CodeAnalysis;
using Avalonia;
using Avalonia.Controls;
using Avalonia.Controls.ApplicationLifetimes;
using Avalonia.Markup.Xaml;
using Avalonia.Platform;
using Avalonia.Threading;
using Microsoft.Extensions.Configuration;
using VozAta.Worker.Services;
using VozAta.Worker.ViewModels;

namespace VozAta.Worker;

/// <summary>Composition root of VozAta Worker: the only place that knows concrete classes.</summary>
[ExcludeFromCodeCoverage(Justification = "Composition root; covered by the manual check.")]
public partial class App : Application
{
    private static readonly TimeSpan RefreshEvery = TimeSpan.FromSeconds(2);
    private bool _exiting;

    public override void Initialize() => AvaloniaXamlLoader.Load(this);

    public override void OnFrameworkInitializationCompleted()
    {
        if (ApplicationLifetime is IClassicDesktopStyleApplicationLifetime desktop)
        {
            desktop.ShutdownMode = ShutdownMode.OnExplicitShutdown; // the tray keeps it running
            var options = new ConfigurationBuilder()
                .SetBasePath(AppContext.BaseDirectory)
                .AddJsonFile("appsettings.json", optional: true)
                .Build()
                .GetSection("Worker")
                .Get<WorkerOptions>() ?? new WorkerOptions();
            var command = WorkerCommand.Resolve(options, AppContext.BaseDirectory);
            var folder = command?.WorkingDirectory
                ?? Path.GetFullPath(Environment.ExpandEnvironmentVariables(options.WorkingDirectory));
            var process = new SystemWorkerProcess(command);
            var texts = new WorkerTexts();
            var viewModel = new WorkerAppViewModel(
                process,
                new WorkerStatusClient(new HttpClient { Timeout = TimeSpan.FromSeconds(2) }),
                new RegistryStartup(Environment.ProcessPath ?? "VozAta.Worker.exe"),
                new NetshFirewall(),
                texts,
                () => WorkerPorts.Read(Path.Combine(folder, ".env")));

            var window = new WorkerWindow { DataContext = viewModel };
            window.Closing += (_, args) =>
            {
                if (!_exiting)
                {
                    args.Cancel = true; // closing the window keeps the worker running in the tray
                    window.Hide();
                }
            };

            void Exit()
            {
                _exiting = true;
                viewModel.Shutdown();
                desktop.Shutdown();
            }

            AddTrayIcon(window, texts, Exit);
            var timer = new DispatcherTimer { Interval = RefreshEvery };
            timer.Tick += async (_, _) => await viewModel.RefreshAsync();
            timer.Start();
            desktop.ShutdownRequested += (_, _) => viewModel.Shutdown();

            viewModel.StartCommand.Execute(null);
            if (desktop.Args?.Contains("--minimized") != true)
            {
                window.Show();
            }
        }

        base.OnFrameworkInitializationCompleted();
    }

    private void AddTrayIcon(Window window, WorkerTexts texts, Action exit)
    {
        var show = new NativeMenuItem(texts["WorkerTrayShow"]);
        show.Click += (_, _) => Reveal(window);
        var quit = new NativeMenuItem(texts["WorkerTrayExit"]);
        quit.Click += (_, _) => exit();
        var icon = new TrayIcon
        {
            Icon = new WindowIcon(AssetLoader.Open(new Uri("avares://VozAta.Worker/Assets/vozata.ico"))),
            ToolTipText = "VozAta Worker",
            Menu = [show, new NativeMenuItemSeparator(), quit],
        };
        icon.Clicked += (_, _) => Reveal(window);
        TrayIcon.SetIcons(this, [icon]);
    }

    private static void Reveal(Window window)
    {
        window.Show();
        window.WindowState = WindowState.Normal;
        window.Activate();
    }
}
