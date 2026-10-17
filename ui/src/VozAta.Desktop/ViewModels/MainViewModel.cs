using System.Collections.ObjectModel;
using System.ComponentModel;
using CommunityToolkit.Mvvm.ComponentModel;
using CommunityToolkit.Mvvm.Input;
using VozAta.Client;
using VozAta.Desktop.Services;

namespace VozAta.Desktop.ViewModels;

/// <summary>Main window: engine connection, devices, Start/Stop, level meters, languages, live transcript.</summary>
public sealed partial class MainViewModel : ObservableObject, IDisposable
{
    public const double DefaultWidth = 960;
    public const double DefaultHeight = 680;

    /// <summary>Meter animation rate (~30 fps); level events arrive at ~10 Hz per channel.</summary>
    public static readonly TimeSpan MeterInterval = TimeSpan.FromMilliseconds(33);

    private readonly IEngineClient _client;
    private readonly IEngineEvents _events;
    private readonly IEngineProcess _process;
    private readonly IUiDispatcher _dispatcher;
    private readonly IDialogService _dialogs;
    private readonly ILocalizationService _localization;
    private readonly IUiPreferences _preferences;
    private readonly IUiTimer _timer;
    private readonly CancellationTokenSource _stop = new();
    private IDisposable? _meterTicks;
    private string? _micLabel;
    private string? _systemLabel;
    private bool _ready;
    private TaskCompletionSource _idle = NewIdleSignal(completed: true);
    private string? _detectedLanguage;
    private string? _defaultTemplate;
    private string? _liveSessionId; // the session whose lines Segments shows

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
        IFileSaver saver)
    {
        _client = client;
        _events = events;
        _process = process;
        _dispatcher = dispatcher;
        _dialogs = dialogs;
        _localization = localization;
        _preferences = preferences;
        _timer = timer;
        Devices = new DevicesViewModel(client, preferences);
        Templates = new MinutesTemplatesViewModel(client);
        History = new HistoryViewModel(client, shell, localization, saver, Templates, dialogs: dialogs);
        Health = new HealthViewModel(client, localization);
        Settings = new SettingsViewModel(client, process, localization);
        Vocabulary = new VocabularyViewModel(client, localization);
        Tray = new TrayViewModel(this, localization, preferences);
        Recovery = new RecoveryViewModel(client, localization, Notify);
        Settings.Saved += OnSettingsSaved;
        MicMeter = new LevelMeterViewModel(clock, watchSilence: false);
        SystemMeter = new LevelMeterViewModel(clock, watchSilence: true);
        var saved = preferences.Load();
        WindowWidth = saved.WindowWidth ?? DefaultWidth;
        WindowHeight = saved.WindowHeight ?? DefaultHeight;
        L = new Strings(localization);
        ConversationLanguages =
        [
            new("en", "LanguageEn"), new("pt", "LanguagePt"), new("es", "LanguageEs"), new("auto", "LanguageAuto"),
        ];
        AppLanguages = [new("en", "AppLanguageEn"), new("pt-BR", "AppLanguagePtBr"), new("es", "AppLanguageEs")];
        SelectedLanguage = ConversationLanguages[0];
        SelectedAppLanguage = AppLanguages[0];
        localization.PropertyChanged += OnLanguageChanged;
        Segments.CollectionChanged += (_, _) => OnPropertyChanged(nameof(IsTranscriptEmpty));
        Partials.CollectionChanged += (_, _) => OnPropertyChanged(nameof(IsTranscriptEmpty));
        RefreshTexts();
    }

    /// <summary>
    /// Localized strings for the view: <c>{Binding L[Start]}</c>. A new instance per language switch,
    /// because compiled indexer bindings only re-read when the source object changes.
    /// </summary>
    [ObservableProperty]
    public partial Strings L { get; private set; }

    public IReadOnlyList<ChoiceOption> ConversationLanguages { get; }

    public DevicesViewModel Devices { get; }

    /// <summary>Minutes templates for the Start screen and "Regenerate minutes" (phase 20).</summary>
    public MinutesTemplatesViewModel Templates { get; }

    /// <summary>Template of the next recording; preselected from <c>MINUTES_TEMPLATE</c>.</summary>
    [ObservableProperty]
    public partial TemplateOption? SelectedTemplate { get; set; }

    /// <summary>The last template reload after a language change (tests await it).</summary>
    public Task TemplatesRefresh { get; private set; } = Task.CompletedTask;

    public HistoryViewModel History { get; }

    /// <summary>Crash recovery dialog (phase 17), opened by <c>recovery_available</c>.</summary>
    public RecoveryViewModel Recovery { get; }

    /// <summary>The last recovery step started by an event (tests await it).</summary>
    public Task RecoveryRefresh { get; private set; } = Task.CompletedTask;

    /// <summary>The last history reload started by an event (tests await it).</summary>
    public Task HistoryRefresh { get; private set; } = Task.CompletedTask;

    public LevelMeterViewModel MicMeter { get; }

    /// <summary>System audio meter; its <c>NoSignal</c> drives the "check your output device" hint.</summary>
    public LevelMeterViewModel SystemMeter { get; }

    [ObservableProperty]
    public partial double WindowWidth { get; set; }

    [ObservableProperty]
    public partial double WindowHeight { get; set; }

    public IReadOnlyList<ChoiceOption> AppLanguages { get; }

    public ObservableCollection<TranscriptLine> Segments { get; } = [];

    /// <summary>Interim text, at most one line per channel, shown under the transcript.</summary>
    public ObservableCollection<TranscriptLine> Partials { get; } = [];

    public bool IsTranscriptEmpty => Segments.Count == 0 && Partials.Count == 0;

    public ObservableCollection<string> Notifications { get; } = [];

    /// <summary>The running event loop (null until initialized).</summary>
    public Task? EventLoop { get; private set; }

    /// <summary>Events handled so far (lets tests wait for asynchronous delivery).</summary>
    public int HandledEvents { get; private set; }

    [ObservableProperty]
    [NotifyPropertyChangedFor(nameof(StatusText), nameof(IsRecording), nameof(IsPaused), nameof(IsActivelyRecording), nameof(PauseResumeText))]
    [NotifyCanExecuteChangedFor(nameof(StartCommand), nameof(StopCommand), nameof(PauseResumeCommand))]
    public partial RecordingState State { get; private set; } = RecordingState.Idle;

    [ObservableProperty]
    [NotifyPropertyChangedFor(nameof(EngineText))]
    [NotifyCanExecuteChangedFor(nameof(StartCommand))]
    public partial EngineStatus EngineStatus { get; private set; } = EngineStatus.Starting;

    [ObservableProperty]
    public partial string Elapsed { get; private set; } = "00:00:00";

    /// <summary>The engine is still loading the speech model; audio is already being recorded.</summary>
    [ObservableProperty]
    public partial bool IsModelLoading { get; private set; }

    [ObservableProperty]
    public partial ChoiceOption SelectedLanguage { get; set; }

    [ObservableProperty]
    public partial ChoiceOption? SelectedAppLanguage { get; set; }

    [ObservableProperty]
    public partial string? DetectedLanguage { get; private set; }

    public bool IsRecording => State is RecordingState.Recording or RecordingState.Paused;

    /// <summary>Paused: amber indicator, frozen timer, audio not transcribed.</summary>
    public bool IsPaused => State == RecordingState.Paused;

    /// <summary>Recording and not paused: red indicator.</summary>
    public bool IsActivelyRecording => State == RecordingState.Recording;

    public string PauseResumeText => _localization[IsPaused ? "Resume" : "Pause"];

    public string StatusText => _localization[$"State{State}"];

    public string EngineText => EngineStatus switch
    {
        EngineStatus.Connected => _localization["EngineConnected"],
        EngineStatus.Disconnected => _localization["EngineDisconnected"],
        EngineStatus.Failed => _localization["EngineStartFailed"],
        _ => _localization["EngineStarting"],
    };

    /// <summary>GPU, speech and minutes status (status bar and settings page).</summary>
    public HealthViewModel Health { get; }

    public SettingsViewModel Settings { get; }

    /// <summary>The glossary editor on the settings page (phase 19).</summary>
    public VocabularyViewModel Vocabulary { get; }

    /// <summary>"Terms for this meeting" on the Start screen: comma or newline separated (phase 19).</summary>
    [ObservableProperty]
    public partial string SessionTerms { get; set; } = "";

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
            SelectedLanguage = ConversationLanguages.FirstOrDefault(
                option => option.Value == settings.GetString("TRANSCRIPTION_LANGUAGE")) ?? ConversationLanguages[0];
            _micLabel = NonEmpty(settings.GetString("MIC_LABEL"));
            _systemLabel = NonEmpty(settings.GetString("SYSTEM_LABEL"));
            _defaultTemplate = NonEmpty(settings.GetString("MINUTES_TEMPLATE"));
        }
        catch (Exception error) when (error is EngineApiException or EngineUnavailableException)
        {
            Notify(ErrorText(error));
        }

        await LoadTemplatesAsync();

        try
        {
            await Devices.LoadAsync(_stop.Token);
        }
        catch (Exception error) when (error is EngineApiException or EngineUnavailableException)
        {
            Notify(ErrorText(error)); // recording still works with the engine's default devices
        }

        await History.LoadAsync(_stop.Token);
        await Settings.LoadAsync(_stop.Token);
        await Vocabulary.LoadAsync(_stop.Token);

        RefreshTexts();
        _ready = true;
        EventLoop = FollowEventsAsync();
    }

    /// <summary>Whether the window may close: asks about unsaved transcript edits, and while recording asks and stops the session first.</summary>
    public async Task<bool> ConfirmCloseAsync()
    {
        if (!await History.ConfirmLeaveAsync())
        {
            return false; // unsaved transcript edits (phase 21)
        }

        if (!IsRecording)
        {
            return true;
        }

        var confirmed = await _dialogs.ConfirmAsync(
            _localization["ConfirmCloseTitle"], _localization["ConfirmCloseMessage"], _localization["ConfirmCloseYes"], _localization["ConfirmCloseNo"]);
        if (confirmed)
        {
            await StopAsync();
        }

        return confirmed;
    }

    /// <summary>Wait (at most <paramref name="maxWait"/>) for finalization, then release the engine.</summary>
    public async Task ShutdownAsync(TimeSpan maxWait)
    {
        _preferences.Save(_preferences.Load() with { WindowWidth = WindowWidth, WindowHeight = WindowHeight });
        await Task.WhenAny(_idle.Task, Task.Delay(maxWait));
        await _stop.CancelAsync();
        _process.StopIfStarted();
    }

    public void Dispose()
    {
        _localization.PropertyChanged -= OnLanguageChanged;
        _meterTicks?.Dispose();
        _stop.Dispose();
    }

    private bool CanStart() => State == RecordingState.Idle && EngineStatus == EngineStatus.Connected;

    private bool CanStop() => IsRecording;

    /// <summary>Pause while recording, resume while paused (the window button and the tray).</summary>
    [RelayCommand(CanExecute = nameof(CanStop))]
    private async Task PauseResumeAsync()
    {
        var resume = IsPaused;
        try
        {
            if (resume)
            {
                await _client.ResumeSessionAsync(_stop.Token);
            }
            else
            {
                await _client.PauseSessionAsync(_stop.Token);
            }

            SetState(resume ? RecordingState.Recording : RecordingState.Paused);
        }
        catch (Exception error) when (error is EngineApiException or EngineUnavailableException)
        {
            Notify(ErrorText(error));
        }
    }

    [RelayCommand(CanExecute = nameof(CanStart))]
    private async Task StartAsync()
    {
        Segments.Clear();
        _liveSessionId = null;
        Partials.Clear();
        DetectedLanguage = _detectedLanguage = null;
        Elapsed = TranscriptLine.FormatTime(0);
        SetState(RecordingState.Starting);
        try
        {
            var terms = VocabularyViewModel.ParseTerms(SessionTerms);
            var request = new StartSessionRequest(
                Devices.MicDeviceId, Devices.SystemDeviceId, SelectedLanguage.Value, SelectedTemplate?.Id,
                terms.Count > 0 ? terms : null);
            await _client.StartSessionAsync(request, _stop.Token);
            SetState(RecordingState.Recording);
        }
        catch (Exception error) when (error is EngineApiException or EngineUnavailableException)
        {
            Notify(ErrorText(error));
            SetState(RecordingState.Idle);
        }
    }

    [RelayCommand(CanExecute = nameof(CanStop))]
    private async Task StopAsync()
    {
        try
        {
            await _client.StopSessionAsync(_stop.Token);
            SetState(RecordingState.Finalizing);
        }
        catch (Exception error) when (error is EngineApiException or EngineUnavailableException)
        {
            Notify(ErrorText(error));
        }
    }

    [RelayCommand]
    private void DismissNotification(string message) => Notifications.Remove(message);

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

        await LoadTemplatesAsync(); // template names follow APP_LANGUAGE
    }

    /// <summary>Load (or rename) the templates and keep a valid selection.</summary>
    private async Task LoadTemplatesAsync()
    {
        try
        {
            await Templates.LoadAsync(_stop.Token);
        }
        catch (Exception error) when (error is EngineApiException or EngineUnavailableException)
        {
            Notify(ErrorText(error)); // recording still works with the engine's default template
            return;
        }

        if (SelectedTemplate is null || !Templates.Items.Contains(SelectedTemplate))
        {
            SelectedTemplate = Templates.Find(_defaultTemplate) ?? Templates.Items.FirstOrDefault();
        }
    }

    /// <summary>Apply saved settings the window shows: languages and speaker labels.</summary>
    private void OnSettingsSaved(IReadOnlyDictionary<string, string?> values)
    {
        if (values.TryGetValue("TRANSCRIPTION_LANGUAGE", out var conversation) && !IsRecording
            && ConversationLanguages.FirstOrDefault(option => option.Value == conversation) is { } option)
        {
            SelectedLanguage = option;
        }

        if (values.TryGetValue("MIC_LABEL", out var mic))
        {
            _micLabel = NonEmpty(mic);
        }

        if (values.TryGetValue("SYSTEM_LABEL", out var system))
        {
            _systemLabel = NonEmpty(system);
        }

        if (values.TryGetValue("MINUTES_TEMPLATE", out var template))
        {
            _defaultTemplate = NonEmpty(template);
            if (!IsRecording && Templates.Find(_defaultTemplate) is { } chosen)
            {
                SelectedTemplate = chosen;
            }
        }

        if (values.ContainsKey("APP_LANGUAGE"))
        {
            TemplatesRefresh = LoadTemplatesAsync();
        }

        if (values.TryGetValue("APP_LANGUAGE", out var language) && language is not null && language != _localization.Language)
        {
            _localization.SetLanguage(language); // refreshes every text
        }
        else
        {
            RefreshTexts();
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
                    History.Ask.OnConnectionLost();
                    Recovery.OnConnectionLost();
                }

                break;
            case AnswerChunkEvent chunk:
                History.Ask.OnAnswerChunk(chunk);
                break;
            case AnswerDoneEvent done:
                History.Ask.OnAnswerDone(done);
                break;
            case StatusEvent status:
                OnStatus(status);
                RecoveryRefresh = Recovery.OnStatusAsync(status);
                break;
            case RecoveryAvailableEvent offer:
                RecoveryRefresh = Recovery.OfferAsync(offer.SessionIds);
                break;
            case SegmentEvent { Segment: var segment } segmentEvent:
                _liveSessionId = segmentEvent.SessionId ?? _liveSessionId;
                RemovePartial(segment.Channel);
                Segments.Add(new TranscriptLine(
                    TranscriptLine.FormatTime(segment.Start), segment.Label, segment.Text, segment.Channel));
                break;
            case PartialEvent partial:
                OnPartial(partial);
                break;
            case LevelEvent { Channel: "mic" } level:
                MicMeter.OnLevel(level.RmsDb);
                break;
            case LevelEvent { Channel: "system" } level:
                SystemMeter.OnLevel(level.RmsDb);
                break;
            case LanguageDetectedEvent detected:
                _detectedLanguage = detected.Language;
                RefreshDetectedLanguage();
                break;
            case ModelLoadingEvent loading:
                IsModelLoading = loading.Loading;
                break;
            case MinutesReadyEvent minutes:
                Notify(_localization["MinutesReady"]);
                HistoryRefresh = History.OnMinutesReadyAsync(minutes.SessionId);
                break;
            case SpeakersRelabeledEvent relabeled:
                HistoryRefresh = OnSpeakersRelabeledAsync(relabeled.SessionId);
                break;
            case ErrorEvent error:
                Notify(error.Message);
                History.OnError(error.SessionId, error.Message);
                RecoveryRefresh = Recovery.OnErrorAsync(error);
                break;
        }

        HandledEvents++;
    }

    /// <summary>A <c>speakers_relabeled</c> event: show the final speakers in the live lines and the open detail.</summary>
    private async Task OnSpeakersRelabeledAsync(string? sessionId)
    {
        if (sessionId is not null && sessionId == _liveSessionId)
        {
            try
            {
                var transcript = await _client.GetTranscriptAsync(sessionId, _stop.Token);
                if (sessionId == _liveSessionId)
                {
                    Segments.Clear();
                    foreach (var segment in transcript.Segments)
                    {
                        Segments.Add(new TranscriptLine(
                            TranscriptLine.FormatTime(segment.Start), segment.Label, segment.Text, segment.Channel));
                    }
                }
            }
            catch (Exception error) when (error is EngineApiException or EngineUnavailableException)
            {
                Notify(ErrorText(error));
            }
        }

        await History.OnSpeakersRelabeledAsync(sessionId);
    }

    private void OnPartial(PartialEvent partial)
    {
        if (partial.Text.Length == 0)
        {
            RemovePartial(partial.Channel);
            return;
        }

        var line = new TranscriptLine(TranscriptLine.FormatTime(partial.Start), partial.Label, partial.Text, partial.Channel);
        var index = PartialIndex(partial.Channel);
        if (index < 0)
        {
            Partials.Add(line);
        }
        else
        {
            Partials[index] = line;
        }
    }

    private void RemovePartial(string channel)
    {
        var index = PartialIndex(channel);
        if (index >= 0)
        {
            Partials.RemoveAt(index);
        }
    }

    private int PartialIndex(string channel)
    {
        for (var i = 0; i < Partials.Count; i++)
        {
            if (Partials[i].Channel == channel)
            {
                return i;
            }
        }

        return -1;
    }

    private void OnStatus(StatusEvent status)
    {
        // The engine clock keeps running while paused (WAVs record silence); the display freezes
        // and continues from the engine clock on resume, matching the transcript timestamps.
        if (status.DurationSeconds is { } seconds && !(IsPaused && status.Status == "paused"))
        {
            Elapsed = TranscriptLine.FormatTime(seconds);
        }

        SetState(status.Status switch
        {
            "recording" => RecordingState.Recording,
            "paused" => RecordingState.Paused,
            "finalizing" => RecordingState.Finalizing,
            _ => RecordingState.Idle, // idle, done, interrupted
        });
    }

    private void SetState(RecordingState state)
    {
        if (state != RecordingState.Idle && _idle.Task.IsCompleted)
        {
            _idle = NewIdleSignal(completed: false);
        }

        var wasRecording = IsRecording;
        var wasIdle = State == RecordingState.Idle;
        State = state;
        if (IsRecording && !wasRecording || state == RecordingState.Idle && !wasIdle)
        {
            HistoryRefresh = History.LoadAsync(); // a session appeared or finished
        }

        Devices.IsEnabled = state == RecordingState.Idle;
        UpdateMeters(wasRecording);
        if (state == RecordingState.Idle)
        {
            IsModelLoading = false;
            Partials.Clear();
            _idle.TrySetResult();
        }
    }

    /// <summary>Meters run (and tick) only while recording or paused; silence is watched only while recording.</summary>
    private void UpdateMeters(bool wasRecording)
    {
        if (!IsRecording)
        {
            _meterTicks?.Dispose();
            _meterTicks = null;
            MicMeter.End();
            SystemMeter.End();
            return;
        }

        if (!wasRecording)
        {
            MicMeter.Begin();
            SystemMeter.Begin();
            _meterTicks = _timer.Start(MeterInterval, TickMeters);
        }

        var recording = State == RecordingState.Recording;
        MicMeter.SetActive(recording);
        SystemMeter.SetActive(recording);
    }

    private void TickMeters()
    {
        MicMeter.Tick();
        SystemMeter.Tick();
    }

    private static string? NonEmpty(string? text) => string.IsNullOrWhiteSpace(text) ? null : text;

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
        Settings.RefreshTexts();
    }

    private void RefreshTexts()
    {
        foreach (var option in ConversationLanguages.Concat(AppLanguages))
        {
            option.Refresh(_localization);
        }

        RefreshDetectedLanguage();
        MicMeter.Label = _micLabel ?? _localization["SpeakerMic"];
        SystemMeter.Label = _systemLabel ?? _localization["SpeakerSystem"];
        OnPropertyChanged(nameof(StatusText));
        OnPropertyChanged(nameof(PauseResumeText));
        OnPropertyChanged(nameof(EngineText));
        Health.RefreshTexts();
    }

    private void RefreshDetectedLanguage()
    {
        var option = ConversationLanguages.FirstOrDefault(language => language.Value == _detectedLanguage);
        DetectedLanguage = option is null ? null : _localization.Format("DetectedLanguage", option.Label);
    }

    private static TaskCompletionSource NewIdleSignal(bool completed)
    {
        var signal = new TaskCompletionSource(TaskCreationOptions.RunContinuationsAsynchronously);
        if (completed)
        {
            signal.SetResult();
        }

        return signal;
    }
}
