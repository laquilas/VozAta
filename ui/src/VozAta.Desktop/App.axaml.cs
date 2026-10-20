using System.Diagnostics.CodeAnalysis;
using Avalonia;
using Avalonia.Controls;
using Avalonia.Controls.ApplicationLifetimes;
using Avalonia.Controls.Primitives;
using Avalonia.Markup.Xaml;
using Avalonia.Platform;
using Microsoft.Extensions.Configuration;
using Microsoft.Extensions.DependencyInjection;
using VozAta.Client;
using VozAta.Desktop.Services;
using VozAta.Desktop.ViewModels;
using VozAta.Desktop.Views;

namespace VozAta.Desktop;

/// <summary>Composition root: the only place that knows concrete classes.</summary>
[ExcludeFromCodeCoverage(Justification = "Composition root; covered by the manual check.")]
public partial class App : Application
{
    /// <summary>Longest wait for the recorder to stop when the window closes; background processing is not waited for (phase 40).</summary>
    private static readonly TimeSpan StopWait = TimeSpan.FromSeconds(15);

    public override void Initialize()
    {
        AvaloniaXamlLoader.Load(this);
    }

    public override void OnFrameworkInitializationCompleted()
    {
        if (ApplicationLifetime is IClassicDesktopStyleApplicationLifetime desktop)
        {
#if DEBUG
            if (desktop.Args?.Contains("--theme-gallery") == true)
            {
                // Design review (phase 34): every token and style in both themes, no engine.
                desktop.MainWindow = new Diagnostics.ThemeGalleryWindow();
                base.OnFrameworkInitializationCompleted();
                return;
            }
#endif

            var services = ConfigureServices(desktop);
            var viewModel = services.GetRequiredService<MainViewModel>();
            var window = new MainWindow { DataContext = viewModel };
            desktop.MainWindow = window;
            GuardClosing(window, viewModel);
            AddTrayIcon(window, viewModel.Tray);
            _ = viewModel.InitializeAsync();
        }

        base.OnFrameworkInitializationCompleted();
    }

    private static ServiceProvider ConfigureServices(IClassicDesktopStyleApplicationLifetime desktop)
    {
        var configuration = new ConfigurationBuilder()
            .SetBasePath(AppContext.BaseDirectory)
            .AddJsonFile("appsettings.json", optional: true)
            .Build();
        var options = configuration.GetSection("Engine").Get<EngineOptions>() ?? new EngineOptions();
        var baseUri = new Uri(options.BaseUrl);
        var socketUri = new UriBuilder(baseUri) { Scheme = baseUri.Scheme == "https" ? "wss" : "ws", Path = "ws" }.Uri;

        var services = new ServiceCollection();
        services.AddSingleton(options);
        services.AddSingleton(_ => new HttpClient { BaseAddress = baseUri, Timeout = TimeSpan.FromMinutes(5) });
        services.AddSingleton<IEngineClient, EngineClient>();
        services.AddSingleton<IEngineEvents>(_ => new EngineEvents(socketUri, new ClientWebSocketConnector()));
        services.AddSingleton<IProcessRunner, SystemProcessRunner>();
        services.AddSingleton(_ => PathResolver.ForProcess());
        services.AddSingleton<IEngineProcess>(provider => new EngineProcess(
            provider.GetRequiredService<IEngineClient>(),
            provider.GetRequiredService<IProcessRunner>(),
            options,
            provider.GetRequiredService<PathResolver>()));
        services.AddSingleton<IUiDispatcher, AvaloniaUiDispatcher>();
        services.AddSingleton<ILocalizationService, LocalizationService>();
        services.AddSingleton<IDialogService>(_ => new AvaloniaDialogService(desktop));
        services.AddSingleton<IUiPreferences>(_ => new JsonFileUiPreferences(JsonFileUiPreferences.DefaultPath()));
        services.AddSingleton<IClock, SystemClock>();
        services.AddSingleton<IUiTimer, AvaloniaUiTimer>();
        services.AddSingleton<IShellService, ShellService>();
        services.AddSingleton<IFileSaver>(_ => new AvaloniaFileSaver(desktop));
        services.AddSingleton<IPathPicker>(_ => new AvaloniaPathPicker(desktop));
        services.AddSingleton<IThemeService, AvaloniaThemeService>();
        services.AddSingleton<Func<IAudioPlayer>>(_ => () => new LibVlcAudioPlayer()); // one per meeting page (37)
        services.AddSingleton(baseUri); // the player streams GET /sessions/{id}/audio/{track} from here
        services.AddSingleton<IProcessingMarkers, ProcessingMarkers>(); // done checks on the meetings list (phase 40)
        services.AddSingleton<MainViewModel>();
        return services.BuildServiceProvider();
    }

    /// <summary>The tray icon and menu mirror <see cref="TrayViewModel"/>; minimizing can hide the window.</summary>
    private void AddTrayIcon(Window window, TrayViewModel tray)
    {
        var icons = Enum.GetValues<TrayState>().ToDictionary(
            state => state,
            state => new WindowIcon(AssetLoader.Open(AppIcons.ForTray(state))));
        var start = new NativeMenuItem { Command = tray.StartCommand };
        var pauseResume = new NativeMenuItem { Command = tray.PauseResumeCommand };
        var stop = new NativeMenuItem { Command = tray.StopCommand };
        var show = new NativeMenuItem { Command = tray.ShowCommand };
        var quit = new NativeMenuItem { Command = tray.QuitCommand };
        var icon = new TrayIcon
        {
            Menu = [start, pauseResume, stop, new NativeMenuItemSeparator(), show, quit],
        };

        void Refresh()
        {
            icon.Icon = icons[tray.State];
            icon.ToolTipText = tray.ToolTip;
            (start.Header, pauseResume.Header, stop.Header) = (tray.StartText, tray.PauseResumeText, tray.StopText);
            (show.Header, quit.Header) = (tray.ShowText, tray.QuitText);
        }

        void ShowWindow()
        {
            window.Show();
            window.WindowState = WindowState.Normal;
            window.Activate();
        }

        Refresh();
        tray.PropertyChanged += (_, _) => Refresh();
        tray.ShowRequested += ShowWindow;
        tray.QuitRequested += () =>
        {
            ShowWindow();
            window.Close(); // asks first while recording (GuardClosing)
        };
        icon.Clicked += (_, _) => ShowWindow();
        window.PropertyChanged += (_, args) =>
        {
            if (args.Property == Window.WindowStateProperty && window.WindowState == WindowState.Minimized && tray.MinimizeToTray)
            {
                window.Hide();
            }
        };
        TrayIcon.SetIcons(this, [icon]);
    }

    /// <summary>Closing asks while recording and warns about pending processing, then stops the engine.</summary>
    private static void GuardClosing(Window window, MainViewModel viewModel)
    {
        var closing = false;
        var confirming = false;
        window.Closing += async (_, args) =>
        {
            if (closing)
            {
                return;
            }

            args.Cancel = true;
            if (confirming)
            {
                return; // a second close request while a dialog is open must not stack another
            }

            confirming = true;
            bool confirmed;
            try
            {
                confirmed = await viewModel.ConfirmCloseAsync();
            }
            finally
            {
                confirming = false;
            }

            if (!confirmed)
            {
                return;
            }

            closing = true;
            window.IsEnabled = false;
            await viewModel.ShutdownAsync(StopWait);
            window.Close();
        };
    }
}
