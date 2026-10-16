using System.Diagnostics.CodeAnalysis;
using Avalonia;
using Avalonia.Controls;
using Avalonia.Controls.ApplicationLifetimes;
using Avalonia.Markup.Xaml;
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
    /// <summary>Longest wait for a finalizing session when the window closes.</summary>
    private static readonly TimeSpan FinalizeWait = TimeSpan.FromMinutes(10);

    public override void Initialize()
    {
        AvaloniaXamlLoader.Load(this);
    }

    public override void OnFrameworkInitializationCompleted()
    {
        if (ApplicationLifetime is IClassicDesktopStyleApplicationLifetime desktop)
        {
            var services = ConfigureServices(desktop);
            var viewModel = services.GetRequiredService<MainViewModel>();
            var window = new MainWindow { DataContext = viewModel };
            desktop.MainWindow = window;
            GuardClosing(window, viewModel);
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
        services.AddSingleton<MainViewModel>();
        return services.BuildServiceProvider();
    }

    /// <summary>Closing asks while recording, then waits for finalization before the engine stops.</summary>
    private static void GuardClosing(Window window, MainViewModel viewModel)
    {
        var closing = false;
        window.Closing += async (_, args) =>
        {
            if (closing)
            {
                return;
            }

            args.Cancel = true;
            if (!await viewModel.ConfirmCloseAsync())
            {
                return;
            }

            closing = true;
            window.IsEnabled = false;
            await viewModel.ShutdownAsync(FinalizeWait);
            window.Close();
        };
    }
}
