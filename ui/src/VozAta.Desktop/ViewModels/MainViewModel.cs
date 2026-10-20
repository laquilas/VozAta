using System.Collections.ObjectModel;
using System.ComponentModel;
using CommunityToolkit.Mvvm.ComponentModel;
using CommunityToolkit.Mvvm.Input;
using VozAta.Client;
using VozAta.Desktop.Services;

namespace VozAta.Desktop.ViewModels;

/// <summary>
/// The main window: engine connection and events, notifications, crash recovery, tray, interface
/// language and window size. The pages (recorder, history, settings) own everything else.
/// </summary>
public sealed partial class MainViewModel : ObservableObject, IDisposable
{
    public const double DefaultWidth = 960;
    public const double DefaultHeight = 680;

    /// <summary>Meter animation rate (~30 fps); see <see cref="RecorderPageViewModel.MeterInterval"/>.</summary>
    public static readonly TimeSpan MeterInterval = RecorderPageViewModel.MeterInterval;

    private readonly IEngineClient _client;
    private readonly IEngineEvents _events;
    private readonly IEngineProcess _process;
    private readonly IUiDispatcher _dispatcher;
    private readonly ILocalizationService _localization;
    private readonly IDialogService _dialogs;
    private readonly IUiPreferences _preferences;
    private readonly CancellationTokenSource _stop = new();
    private bool _ready;
    private RecordingState _shownState = RecordingState.Idle; // the last state the history saw

    public MainViewModel(
        IEngineClient client,
        IEngineEvents events,
        IEngineProcess process,
        IUiDispatcher dispatcher,
        ILocalizationService localization,
        IDialogService dialogs,
        IUiPreferences preferences,
        IClock clock,
        IUiTimer timer,
        IShellService shell,
        IFileSaver saver,
        IThemeService theme,
        IPathPicker? paths = null,
        Func<IAudioPlayer>? players = null,
        Uri? engineUri = null,
        IProcessingMarkers? markers = null)
    {
        markers ??= new ProcessingMarkers();
        _client = client;
        _events = events;
        _process = process;
        _dispatcher = dispatcher;
        _dialogs = dialogs;
        _localization = localization;
        _preferences = preferences;
        Session = new RecordingSessionService();
        var templates = new MinutesTemplatesViewModel(client);
        Recorder = new RecorderPageViewModel(
            client, localization, preferences, clock, timer, templates, Session, Notify, cancellation: _stop.Token);
        History = new HistoryViewModel(client, shell, localization, saver, templates, dialogs: dialogs, markers: markers);
        Health = new HealthViewModel(client, localization);
        Processing = new ProcessingIndicatorViewModel(localization);
        Settings = new SettingsViewModel(client, process, localization, paths);
        Vocabulary = new VocabularyViewModel(client, localization);
        Tray = new TrayViewModel(Recorder, localization, preferences);
        Appearance = new AppearanceViewModel(preferences, theme, localization);
        Recovery = new RecoveryViewModel(client, localization, Notify);
        Meetings = new MeetingsPageViewModel(client, History, localization, clock, dialogs, shell, saver, templates, markers: markers);
        History.Players = players is null ? null : (id, tracks) => new PlayerBarViewModel(
            players(), dispatcher, track => AudioUri(engineUri, id, track), tracks, localization);
        History.Renamed = Meetings.OnRenamedAsync;
        History.DeleteMeeting = Meetings.DeleteMeetingAsync;
        History.PropertyChanged += OnHistoryChanged;
        Migration = new MigrationViewModel(client, localization, () => Task.WhenAll(History.LoadAsync(), Meetings.LoadAsync()));
        Shell = new ShellViewModel(
            Recorder,
            Meetings,
            new AskPageViewModel(History.Ask, () => Shell?.NavigateCommand.Execute(ShellViewModel.Meetings)),
            Config = new ConfigPageViewModel(
                Settings, new StorageViewModel(client, shell, dialogs, localization), new AboutViewModel(Health, shell), localization),
            Session,
            localization,
            preferences);
        Shell.SessionLeft += OnSessionLeft;
        Settings.Saved += OnSettingsSaved;
        Session.PropertyChanged += OnSessionChanged;
        var saved = preferences.Load();
        WindowWidth = saved.WindowWidth ?? DefaultWidth;
        WindowHeight = saved.WindowHeight ?? DefaultHeight;
        L = new Strings(localization);
        AppLanguages = [new("en", "AppLanguageEn"), new("pt-BR", "AppLanguagePtBr"), new("es", "AppLanguageEs")];
        SelectedAppLanguage = AppLanguages[0];
        localization.PropertyChanged += OnLanguageChanged;
        RefreshTexts();
    }

    /// <summary>
    /// Localized strings for the views: <c>{Binding L[Start]}</c>. A new instance per language switch,
    /// because compiled indexer bindings only re-read when the source object changes.
    /// </summary>
    [ObservableProperty]
    public partial Strings L { get; private set; }

    /// <summary>The recording every page shows (state, elapsed time, title).</summary>
    public RecordingSessionService Session { get; }

    /// <summary>The Recorder page: Start / Stop, options, meters, live transcript.</summary>
    public RecorderPageViewModel Recorder { get; }

    /// <summary>The sidebar and the current page (phase 35).</summary>
    public ShellViewModel Shell { get; }

    public HistoryViewModel History { get; }

    /// <summary>The sidebar indicator of the background processing queue (phase 40).</summary>
    public ProcessingIndicatorViewModel Processing { get; }

    /// <summary>Meetings still queued, running or paused; closing the app interrupts them until the next start.</summary>
    public int PendingProcessing => Processing.PendingCount;

    /// <summary>The Meetings page (phase 36): meetings by day, with the history detail on the right.</summary>
    public MeetingsPageViewModel Meetings { get; }

    /// <summary>The theme picker of Settings → Desktop app (phase 34).</summary>
    public AppearanceViewModel Appearance { get; }

    /// <summary>Crash recovery dialog (phase 17), opened by <c>recovery_available</c>.</summary>
    public RecoveryViewModel Recovery { get; }

    /// <summary>The import of the old meeting folders (phase 33): banner, counts and errors.</summary>
    public MigrationViewModel Migration { get; }

    /// <summary>The last migration refresh started by an event (tests await it).</summary>
    public Task MigrationRefresh { get; private set; } = Task.CompletedTask;

    /// <summary>The last recovery step started by an event (tests await it).</summary>
    public Task RecoveryRefresh { get; private set; } = Task.CompletedTask;

    /// <summary>The last history reload started by an event (tests await it).</summary>
    public Task HistoryRefresh { get; private set; } = Task.CompletedTask;

    [ObservableProperty]
    public partial double WindowWidth { get; set; }

    [ObservableProperty]
    public partial double WindowHeight { get; set; }

    public IReadOnlyList<ChoiceOption> AppLanguages { get; }

    [ObservableProperty]
    public partial ChoiceOption? SelectedAppLanguage { get; set; }

    public ObservableCollection<string> Notifications { get; } = [];

    /// <summary>The running event loop (null until initialized).</summary>
    public Task? EventLoop { get; private set; }

    /// <summary>Events handled so far (lets tests wait for asynchronous delivery).</summary>
    public int HandledEvents { get; private set; }

    [ObservableProperty]
    [NotifyPropertyChangedFor(nameof(EngineText), nameof(IsEngineConnected), nameof(IsEngineDown))]
    public partial EngineStatus EngineStatus { get; private set; } = EngineStatus.Starting;

    public bool IsEngineConnected => EngineStatus == EngineStatus.Connected;

    /// <summary>The engine dropped or failed to start (red dot in the sidebar).</summary>
    public bool IsEngineDown => EngineStatus is EngineStatus.Disconnected or EngineStatus.Failed;

    public string EngineText => EngineStatus switch
    {
        EngineStatus.Connected => _localization["EngineConnected"],
        EngineStatus.Disconnected => _localization["EngineDisconnected"],
        EngineStatus.Failed => _localization["EngineStartFailed"],
        _ => _localization["EngineStarting"],
    };

    /// <summary>GPU, speech and minutes status (sidebar and settings page).</summary>
    public HealthViewModel Health { get; }

    public SettingsViewModel Settings { get; }

    /// <summary>The Config page (phase 38): sections, search, storage and about.</summary>
    public ConfigPageViewModel Config { get; }

    /// <summary>The glossary editor on the settings page (phase 19).</summary>
    public VocabularyViewModel Vocabulary { get; }

    /// <summary>The system-tray menu (built into a tray icon by the composition root).</summary>
    public TrayViewModel Tray { get; }

    /// <summary>The last save of the interface language (tests await it).</summary>
    public Task LanguageSave { get; private set; } = Task.CompletedTask;

    /// <summary>Connect to (or start) the engine, load its settings, then follow its events.</summary>
    public async Task InitializeAsync()
    {
        EngineStatus = EngineStatus.Starting;
        if (await _process.EnsureRunningAsync(_stop.Token) == EngineStartResult.Failed)
        {
            EngineStatus = EngineStatus.Failed;
            Notify(_localization["EngineStartFailed"]);
            return;
        }

        await Health.LoadAsync(_stop.Token);
        if (Health.Error is { } healthError)
        {
            Notify(healthError);
        }

        try
        {
            var settings = await _client.GetSettingsAsync(_stop.Token);
            SelectedAppLanguage = AppLanguages.FirstOrDefault(
                option => option.Value == settings.GetString("APP_LANGUAGE")) ?? AppLanguages[0];
            Recorder.ApplySettings(settings);
        }
        catch (Exception error) when (error is EngineApiException or EngineUnavailableException)
        {
            Notify(ErrorText(error));
        }

        await Recorder.LoadTemplatesAsync();
        await Recorder.LoadDevicesAsync(); // recording still works with the engine's default devices
        await History.LoadAsync(_stop.Token);
        await Meetings.LoadAsync(_stop.Token);
        await Config.LoadAsync(_stop.Token); // settings, option lists, storage
        await Vocabulary.LoadAsync(_stop.Token);

        RefreshTexts();
        _ready = true;
        EventLoop = FollowEventsAsync();
    }

    /// <summary>Whether the window may close: asks about unsaved transcript edits, while recording asks and stops the session first, and warns once when meetings are still being processed.</summary>
    public async Task<bool> ConfirmCloseAsync()
    {
        if (!await History.ConfirmLeaveAsync())
        {
            return false; // unsaved transcript edits (phase 21)
        }

        // Every question comes before anything is stopped: cancelling at any point changes nothing.
        var recording = Session.IsRecording;
        if (recording && !await _dialogs.ConfirmAsync(
            _localization["ConfirmCloseTitle"], _localization["ConfirmCloseMessage"], _localization["ConfirmCloseYes"], _localization["ConfirmCloseNo"]))
        {
            return false;
        }

        // Pending background processing resumes on the next start (the engine re-queues it): tell the user once.
        // The meeting being recorded joins the queue at Stop, so it counts too.
        var pending = PendingProcessing + (recording ? 1 : 0);
        if (pending > 0 && !await _dialogs.ConfirmAsync(
            _localization["AppTitle"], _localization.Format("Close_PendingProcessing", pending), _localization["TrayQuit"], _localization["ConfirmRevertNo"]))
        {
            return false;
        }

        if (recording)
        {
            await Recorder.StopCommand.ExecuteAsync(null);
        }

        return true;
    }

    /// <summary>Save the window size, commit a pending delete, wait (at most <paramref name="maxWait"/>) for the recorder to stop, then release the engine. Background processing is not waited for.</summary>
    public async Task ShutdownAsync(TimeSpan maxWait)
    {
        _preferences.Save(_preferences.Load() with { WindowWidth = WindowWidth, WindowHeight = WindowHeight });
        await Meetings.CommitPendingAsync(); // a delete still offering "Undo" goes ahead
        await Task.WhenAny(Recorder.Idle, Task.Delay(maxWait));
        await _stop.CancelAsync();
        _process.StopIfStarted();
    }

    public void Dispose()
    {
        _localization.PropertyChanged -= OnLanguageChanged;
        Session.PropertyChanged -= OnSessionChanged;
        Recorder.Dispose();
        Meetings.Dispose();
        Shell.Dispose();
        _stop.Dispose();
    }

    [RelayCommand]
    private void DismissNotification(string message) => Notifications.Remove(message);

    partial void OnEngineStatusChanged(EngineStatus value) => Recorder.IsEngineConnected = value == EngineStatus.Connected;

    partial void OnSelectedAppLanguageChanged(ChoiceOption? value)
    {
        if (value is not null && value.Value != _localization.Language)
        {
            _localization.SetLanguage(value.Value);
            if (_ready)
            {
                LanguageSave = SaveLanguageAsync(value.Value); // the choice also becomes APP_LANGUAGE
            }
        }
    }

    private async Task SaveLanguageAsync(string language)
    {
        try
        {
            await Settings.SaveValueAsync("APP_LANGUAGE", language);
        }
        catch (Exception error) when (error is EngineApiException or EngineUnavailableException)
        {
            Notify(ErrorText(error));
            return;
        }

        await Recorder.LoadTemplatesAsync(); // template names follow APP_LANGUAGE
    }

    /// <summary>Apply saved settings the window shows: languages, speaker labels, template.</summary>
    private void OnSettingsSaved(IReadOnlyDictionary<string, string?> values)
    {
        Recorder.OnSettingsSaved(values);
        if (values.TryGetValue("APP_LANGUAGE", out var language) && language is not null && language != _localization.Language)
        {
            _localization.SetLanguage(language); // refreshes every text
        }
        else
        {
            RefreshTexts();
        }
    }

    /// <summary>The URL of a session track (<c>GET /sessions/{id}/audio/{track}</c>, phase 32).</summary>
    public static Uri AudioUri(Uri? engineUri, string sessionId, string track) =>
        new(engineUri ?? new Uri("http://127.0.0.1:8765/"), $"sessions/{Uri.EscapeDataString(sessionId)}/audio/{track}");

    /// <summary>The last return to the list started by the sidebar (tests await it).</summary>
    public Task SessionClosing { get; private set; } = Task.CompletedTask;

    /// <summary>A meeting opened or closed: show its page, or the list again (phase 37).</summary>
    private void OnHistoryChanged(object? sender, PropertyChangedEventArgs args)
    {
        if (args.PropertyName != nameof(HistoryViewModel.Detail))
        {
            return;
        }

        if (History.Detail is { } page)
        {
            Shell.OpenSession(page);
        }
        else
        {
            Shell.CloseSession();
        }
    }

    private void OnSessionLeft(object? sender, EventArgs args) => SessionClosing = LeaveSessionAsync();

    /// <summary>Another page was chosen while a meeting was open: close it, unless the user keeps unsaved edits.</summary>
    private async Task LeaveSessionAsync()
    {
        if (!await History.CloseAsync() && History.Detail is { } page)
        {
            Shell.OpenSession(page);
        }
    }

    /// <summary>A session appeared or finished: the history reloads.</summary>
    private void OnSessionChanged(object? sender, PropertyChangedEventArgs args)
    {
        if (args.PropertyName != nameof(RecordingSessionService.State))
        {
            return;
        }

        var wasRecording = _shownState is RecordingState.Recording or RecordingState.Paused;
        var wasIdle = _shownState == RecordingState.Idle;
        _shownState = Session.State;
        if (Session.IsRecording && !wasRecording || Session.IsIdle && !wasIdle)
        {
            HistoryRefresh = Task.WhenAll(History.LoadAsync(), Meetings.LoadAsync());
        }
    }

    private async Task FollowEventsAsync()
    {
        try
        {
            await foreach (var engineEvent in _events.ReadAllAsync(_stop.Token))
            {
                _dispatcher.Post(() => Handle(engineEvent));
            }
        }
        catch (OperationCanceledException)
        {
            // Shutting down.
        }
    }

    private void Handle(EngineEvent engineEvent)
    {
        switch (engineEvent)
        {
            case ConnectionChangedEvent connection:
                EngineStatus = connection.Connected ? EngineStatus.Connected : EngineStatus.Disconnected;
                if (!connection.Connected)
                {
                    Processing.Clear(); // the snapshot on reconnect rebuilds it
                    Meetings.OnConnectionLost(); // the rows' badges too
                    History.Ask.OnConnectionLost();
                    Recovery.OnConnectionLost();
                    Migration.OnConnectionLost();
                }
                else
                {
                    MigrationRefresh = Migration.RefreshAsync();
                }

                break;
            case AnswerChunkEvent chunk:
                History.Ask.OnAnswerChunk(chunk);
                History.Detail?.Ask.OnAnswerChunk(chunk); // the meeting page's Ask tab (phase 37)
                break;
            case AnswerDoneEvent done:
                History.Ask.OnAnswerDone(done);
                History.Detail?.Ask.OnAnswerDone(done);
                break;
            case StatusEvent status:
                var wasIdle = Session.IsIdle;
                Recorder.Handle(status);
                RecoveryRefresh = Recovery.OnStatusAsync(status);
                if (status is { Status: "done", SessionId: { } finished } && (wasIdle || !Session.IsIdle))
                {
                    // A meeting finished in the background: show its minutes and speakers (phase 40).
                    // The recorder going idle already refreshes the list for the one it was recording.
                    HistoryRefresh = Task.WhenAll(History.LoadAsync(), Meetings.OnSessionDoneAsync(finished));
                }

                break;
            case ProcessingEvent processing:
                Processing.OnProcessing(processing);
                HistoryRefresh = processing.Info.State is "done" or "failed"
                    ? Task.WhenAll(History.LoadAsync(), Meetings.OnProcessingAsync(processing))
                    : Meetings.OnProcessingAsync(processing);
                break;
            case MigrationProgressEvent progress:
                Migration.OnProgress(progress);
                break;
            case MigrationDoneEvent done:
                MigrationRefresh = Migration.OnDoneAsync(done);
                break;
            case RecoveryAvailableEvent offer:
                RecoveryRefresh = Recovery.OfferAsync(offer.SessionIds);
                break;
            case MinutesReadyEvent minutes:
                Notify(_localization["MinutesReady"]);
                HistoryRefresh = Task.WhenAll(History.OnMinutesReadyAsync(minutes.SessionId), Meetings.LoadAsync());
                break;
            case ActionItemsReadyEvent ready:
                HistoryRefresh = Task.WhenAll(History.OnActionItemsReadyAsync(ready.SessionId), Meetings.LoadAsync());
                break;
            case SpeakersRelabeledEvent relabeled:
                HistoryRefresh = OnSpeakersRelabeledAsync(relabeled.SessionId);
                break;
            case ErrorEvent error:
                Notify(error.Message);
                History.OnError(error.SessionId, error.Message);
                RecoveryRefresh = Recovery.OnErrorAsync(error);
                break;
            default:
                Recorder.Handle(engineEvent); // segments, partials, levels, languages, model loading
                break;
        }

        HandledEvents++;
    }

    /// <summary>A <c>speakers_relabeled</c> event: show the final speakers in the live lines and the open detail.</summary>
    private async Task OnSpeakersRelabeledAsync(string? sessionId)
    {
        await Recorder.OnSpeakersRelabeledAsync(sessionId);
        await History.OnSpeakersRelabeledAsync(sessionId);
    }

    private void Notify(string message)
    {
        if (!Notifications.Contains(message))
        {
            Notifications.Add(message);
        }
    }

    private string ErrorText(Exception error) =>
        error is EngineUnavailableException ? _localization["EngineUnavailable"] : error.Message;

    private void OnLanguageChanged(object? sender, PropertyChangedEventArgs args)
    {
        SelectedAppLanguage = AppLanguages.FirstOrDefault(option => option.Value == _localization.Language) ?? AppLanguages[0];
        L = new Strings(_localization);
        RefreshTexts();
        History.RefreshTexts();
        Meetings.RefreshTexts();
        Config.RefreshTexts();
        Tray.RefreshTexts();
        Shell.RefreshTexts();
        Processing.RefreshTexts();
        Migration.RefreshTexts();
        History.Detail?.Player?.RefreshTexts();
    }

    private void RefreshTexts()
    {
        foreach (var option in AppLanguages)
        {
            option.Refresh(_localization);
        }

        Recorder.RefreshTexts();
        OnPropertyChanged(nameof(EngineText));
        Health.RefreshTexts();
        Appearance.RefreshTexts();
    }
}
