using System.Collections.ObjectModel;
using System.ComponentModel;
using System.Text.Json;
using CommunityToolkit.Mvvm.ComponentModel;
using CommunityToolkit.Mvvm.Input;
using VozAta.Client;
using VozAta.Desktop.Services;

namespace VozAta.Desktop.ViewModels;

/// <summary>
/// The Recorder page (phase 35): Start / Pause / Stop, the options of the next recording (devices,
/// languages, template, terms), level meters and the live transcript. The recording state itself
/// lives in <see cref="RecordingSessionService"/> so every page can show it.
/// </summary>
public sealed partial class RecorderPageViewModel : ObservableObject, IDisposable
{
    /// <summary>Meter animation rate (~30 fps); level events arrive at ~10 Hz per channel.</summary>
    public static readonly TimeSpan MeterInterval = TimeSpan.FromMilliseconds(33);

    /// <summary>A title edited while recording is sent once typing pauses this long (Enter sends it at once).</summary>
    public static readonly TimeSpan TitleDebounce = TimeSpan.FromMilliseconds(800);

    /// <summary>The engine's limit for a meeting title (phase 35).</summary>
    public const int MaxTitleLength = 200;

    private readonly IEngineClient _client;
    private readonly IUiPreferences _preferences;
    private bool _liveTranscription = true;
    private bool? _recordingLive; // live transcription of the followed recording; null while none
    private readonly ILocalizationService _localization;
    private readonly IUiTimer _timer;
    private readonly Action<string> _notify;
    private readonly CancellationToken _cancellation;
    private readonly Dictionary<string, int> _lineOfSegment = [];
    private IDisposable? _meterTicks;
    private string? _micLabel;
    private string? _systemLabel;
    private string? _detectedLanguage;
    private string? _defaultTemplate;
    private string _defaultTranslation = "off";
    private string? _liveSessionId; // the session whose lines Segments shows
    private string? _lastStoppedId; // never adopted again by a late recording/paused heartbeat
    private TaskCompletionSource _idle = NewIdleSignal(completed: true);
    private readonly Func<TimeSpan, CancellationToken, Task> _titleDelay;
    private CancellationTokenSource? _titleTyping; // the pending debounced title update
    private string? _sentTitle; // the title the engine has for the live session

    /// <param name="titleDelay">Waits out the title debounce (tests pass a controllable one).</param>
    public RecorderPageViewModel(
        IEngineClient client,
        ILocalizationService localization,
        IUiPreferences preferences,
        IClock clock,
        IUiTimer timer,
        MinutesTemplatesViewModel templates,
        RecordingSessionService session,
        Action<string> notify,
        Func<TimeSpan, CancellationToken, Task>? titleDelay = null,
        CancellationToken cancellation = default)
    {
        _titleDelay = titleDelay ?? Task.Delay;
        _client = client;
        _preferences = preferences;
        _liveTranscription = preferences.Load().LiveTranscription ?? true;
        _localization = localization;
        _timer = timer;
        _notify = notify;
        _cancellation = cancellation;
        Session = session;
        Templates = templates;
        Devices = new DevicesViewModel(client, preferences);
        MicMeter = new LevelMeterViewModel(clock, watchSilence: false);
        SystemMeter = new LevelMeterViewModel(clock, watchSilence: true);
        ConversationLanguages =
        [
            new("en", "LanguageEn"), new("pt", "LanguagePt"), new("es", "LanguageEs"), new("auto", "LanguageAuto"),
        ];
        TranslationLanguages =
        [
            new("off", "TranslateOff"), new("en", "LanguageEn"), new("pt", "LanguagePt"), new("es", "LanguageEs"),
        ];
        SelectedLanguage = ConversationLanguages[0];
        SelectedTranslation = TranslationLanguages[0];
        Segments.CollectionChanged += (_, _) => NotifyTranscriptEmpty();
        Partials.CollectionChanged += (_, _) => NotifyTranscriptEmpty();
        session.PropertyChanged += OnSessionChanged;
        RefreshTexts();
    }

    /// <summary>The recording shown on every page (state, elapsed time, title).</summary>
    public RecordingSessionService Session { get; }

    /// <summary>
    /// Localized strings for the page and its flyouts (popups have no window ancestor to reach
    /// <see cref="MainViewModel.L"/>); a new instance per language switch.
    /// </summary>
    [ObservableProperty]
    public partial Strings L { get; private set; }

    public IReadOnlyList<ChoiceOption> ConversationLanguages { get; }

    [ObservableProperty]
    public partial ChoiceOption SelectedLanguage { get; set; }

    /// <summary>"Translate to" choices (phase 29): off, en, pt, es.</summary>
    public IReadOnlyList<ChoiceOption> TranslationLanguages { get; }

    /// <summary>Live translation of the next recording; preselected from <c>TRANSLATE_TO</c>.</summary>
    [ObservableProperty]
    public partial ChoiceOption SelectedTranslation { get; set; }

    public DevicesViewModel Devices { get; }

    /// <summary>Minutes templates for the next recording and "Regenerate minutes" (phase 20).</summary>
    public MinutesTemplatesViewModel Templates { get; }

    /// <summary>Template of the next recording; preselected from <c>MINUTES_TEMPLATE</c>.</summary>
    [ObservableProperty]
    public partial TemplateOption? SelectedTemplate { get; set; }

    /// <summary>The last template reload after a language change (tests await it).</summary>
    public Task TemplatesRefresh { get; private set; } = Task.CompletedTask;

    /// <summary>
    /// "What is this meeting about?" (phase 35): sent with Start, and while recording sent to the
    /// engine once typing pauses or on Enter. Cleared when the recording ends.
    /// </summary>
    [ObservableProperty]
    public partial string Title { get; set; } = "";

    /// <summary>The last title update started by an edit (tests await it).</summary>
    public Task TitleSave { get; private set; } = Task.CompletedTask;

    /// <summary>The title box is editable before and during a recording (not while it starts or finalizes).</summary>
    public bool CanEditTitle => State is RecordingState.Idle or RecordingState.Recording or RecordingState.Paused;

    /// <summary>Devices, languages, template and terms (the chips) apply to the next recording only.</summary>
    public bool CanEditOptions => State == RecordingState.Idle;

    /// <summary>"Terms for this meeting": comma or newline separated (phase 19).</summary>
    [ObservableProperty]
    public partial string SessionTerms { get; set; } = "";

    public LevelMeterViewModel MicMeter { get; }

    /// <summary>System audio meter; its <c>NoSignal</c> drives the "check your output device" hint.</summary>
    public LevelMeterViewModel SystemMeter { get; }

    public ObservableCollection<TranscriptLine> Segments { get; } = [];

    /// <summary>Interim text, at most one line per channel, shown under the transcript.</summary>
    public ObservableCollection<TranscriptLine> Partials { get; } = [];

    public bool IsTranscriptEmpty => Segments.Count == 0 && Partials.Count == 0;

    /// <summary>
    /// Transcribe while recording (phase 41); unchecked, only the audio is recorded and the transcript
    /// is created after Stop. Editable with the other options only; the choice is remembered.
    /// </summary>
    public bool LiveTranscription
    {
        get => _liveTranscription;
        set
        {
            if (CanEditOptions && SetLiveTranscription(value))
            {
                _preferences.Save(_preferences.Load() with { LiveTranscription = value });
            }
        }
    }

    /// <summary>The chip: flips the option (ignored while recording).</summary>
    [RelayCommand]
    private void ToggleLiveTranscription() => LiveTranscription = !LiveTranscription;

    /// <summary>Translation needs live transcription.</summary>
    public bool CanChooseTranslation => CanEditOptions && LiveTranscription;

    /// <summary>
    /// The transcript placeholder says the transcript comes after Stop: only while an audio-only
    /// recording is recording or paused (the chip alone does not change the idle prompt).
    /// </summary>
    public bool IsAudioOnlyNotice => IsRecording && _recordingLive == false && IsTranscriptEmpty;

    /// <summary>The transcript placeholder for the usual case ("Press Start...").</summary>
    public bool IsStartPromptVisible => IsTranscriptEmpty && !IsAudioOnlyNotice;

    /// <summary>The last read of an adopted recording's mode (tests await it).</summary>
    public Task RecordingModeLookup { get; private set; } = Task.CompletedTask;

    /// <summary>The engine is still loading the speech model; audio is already being recorded.</summary>
    [ObservableProperty]
    public partial bool IsModelLoading { get; private set; }

    [ObservableProperty]
    public partial string? DetectedLanguage { get; private set; }

    /// <summary>The engine is connected (set by the window); Start needs it.</summary>
    [ObservableProperty]
    [NotifyCanExecuteChangedFor(nameof(StartCommand))]
    public partial bool IsEngineConnected { get; set; }

    public RecordingState State => Session.State;

    public bool IsRecording => Session.IsRecording;

    public bool IsPaused => Session.IsPaused;

    public bool IsActivelyRecording => Session.IsActivelyRecording;

    public string Elapsed => Session.Elapsed;

    public string PauseResumeText => _localization[IsPaused ? "Resume" : "Pause"];

    public string StatusText => _localization[$"State{State}"];

    /// <summary>Completes when no session is active (shutdown waits for finalization).</summary>
    public Task Idle => _idle.Task;

    /// <summary>Apply the engine settings the page uses: languages, labels, default template and translation.</summary>
    public void ApplySettings(EngineSettings settings)
    {
        SelectedLanguage = ConversationLanguages.FirstOrDefault(
            option => option.Value == settings.GetString("TRANSCRIPTION_LANGUAGE")) ?? ConversationLanguages[0];
        _micLabel = NonEmpty(settings.GetString("MIC_LABEL"));
        _systemLabel = NonEmpty(settings.GetString("SYSTEM_LABEL"));
        _defaultTemplate = NonEmpty(settings.GetString("MINUTES_TEMPLATE"));
        ApplyDefaultTranslation(settings.GetString("TRANSLATE_TO"));
        // The remembered choice wins over LIVE_TRANSCRIPTION until the setting is saved again
        SetLiveTranscription(_preferences.Load().LiveTranscription ?? ParseBool(settings.GetString("LIVE_TRANSCRIPTION")) ?? true);
    }

    /// <summary>Saved settings: languages, labels and template apply when not recording.</summary>
    public void OnSettingsSaved(IReadOnlyDictionary<string, string?> values)
    {
        if (values.TryGetValue("TRANSCRIPTION_LANGUAGE", out var conversation) && !IsRecording
            && ConversationLanguages.FirstOrDefault(option => option.Value == conversation) is { } option)
        {
            SelectedLanguage = option;
        }

        if (values.TryGetValue("TRANSLATE_TO", out var translation) && !IsRecording)
        {
            ApplyDefaultTranslation(translation);
        }

        if (values.TryGetValue("LIVE_TRANSCRIPTION", out var live) && !IsRecording)
        {
            SetLiveTranscription(ParseBool(live) ?? true);
            _preferences.Save(_preferences.Load() with { LiveTranscription = null }); // the setting is the default again
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
    }

    /// <summary>Load (or rename) the templates and keep a valid selection.</summary>
    public async Task LoadTemplatesAsync()
    {
        try
        {
            await Templates.LoadAsync(_cancellation);
        }
        catch (Exception error) when (error is EngineApiException or EngineUnavailableException)
        {
            _notify(ErrorText(error)); // recording still works with the engine's default template
            return;
        }

        if (SelectedTemplate is null || !Templates.Items.Contains(SelectedTemplate))
        {
            SelectedTemplate = Templates.Find(_defaultTemplate) ?? Templates.Items.FirstOrDefault();
        }
    }

    /// <summary>Load the device lists; a failure is shown and recording uses the engine defaults.</summary>
    public async Task LoadDevicesAsync()
    {
        try
        {
            await Devices.LoadAsync(_cancellation);
        }
        catch (Exception error) when (error is EngineApiException or EngineUnavailableException)
        {
            _notify(ErrorText(error));
        }
    }

    /// <summary>The live events of a recording; false for events the page does not use.</summary>
    public bool Handle(EngineEvent engineEvent)
    {
        switch (engineEvent)
        {
            case StatusEvent status:
                OnStatus(status);
                return true;
            case SegmentEvent { Segment: var segment } segmentEvent:
                _liveSessionId = segmentEvent.SessionId ?? _liveSessionId;
                RemovePartial(segment.Channel);
                AddLine(segment);
                return true;
            case TranslationEvent translation:
                OnTranslation(translation);
                return true;
            case PartialEvent partial:
                OnPartial(partial);
                return true;
            case LevelEvent { Channel: "mic" } level:
                MicMeter.OnLevel(level.RmsDb);
                return true;
            case LevelEvent { Channel: "system" } level:
                SystemMeter.OnLevel(level.RmsDb);
                return true;
            case LanguageDetectedEvent detected:
                _detectedLanguage = detected.Language;
                RefreshDetectedLanguage();
                return true;
            case ModelLoadingEvent loading:
                IsModelLoading = loading.Loading;
                return true;
            default:
                return false;
        }
    }

    /// <summary>A <c>speakers_relabeled</c> event: show the final speakers in the live lines.</summary>
    public async Task OnSpeakersRelabeledAsync(string? sessionId)
    {
        if (sessionId is null || sessionId != _liveSessionId)
        {
            return;
        }

        try
        {
            var transcript = await _client.GetTranscriptAsync(sessionId, _cancellation);
            if (sessionId == _liveSessionId)
            {
                Segments.Clear();
                _lineOfSegment.Clear();
                foreach (var segment in transcript.Segments)
                {
                    AddLine(segment); // keeps the live translations (phase 29)
                }
            }
        }
        catch (Exception error) when (error is EngineApiException or EngineUnavailableException)
        {
            _notify(ErrorText(error));
        }
    }

    public void RefreshTexts()
    {
        L = new Strings(_localization);
        foreach (var option in ConversationLanguages.Concat(TranslationLanguages))
        {
            option.Refresh(_localization);
        }

        RefreshDetectedLanguage();
        MicMeter.Label = _micLabel ?? _localization["SpeakerMic"];
        SystemMeter.Label = _systemLabel ?? _localization["SpeakerSystem"];
        OnPropertyChanged(nameof(StatusText));
        OnPropertyChanged(nameof(PauseResumeText));
    }

    public void Dispose()
    {
        Session.PropertyChanged -= OnSessionChanged;
        _meterTicks?.Dispose();
        _titleTyping?.Cancel();
    }

    private bool CanStart() => State == RecordingState.Idle && IsEngineConnected;

    private bool CanStop() => IsRecording;

    /// <summary>Pause while recording, resume while paused (the page button and the tray).</summary>
    [RelayCommand(CanExecute = nameof(CanStop))]
    private async Task PauseResumeAsync()
    {
        var resume = IsPaused;
        try
        {
            if (resume)
            {
                await _client.ResumeSessionAsync(_cancellation);
            }
            else
            {
                await _client.PauseSessionAsync(_cancellation);
            }

            SetState(resume ? RecordingState.Recording : RecordingState.Paused);
        }
        catch (Exception error) when (error is EngineApiException or EngineUnavailableException)
        {
            _notify(ErrorText(error));
        }
    }

    [RelayCommand(CanExecute = nameof(CanStart))]
    private async Task StartAsync()
    {
        Segments.Clear();
        _liveSessionId = null;
        Partials.Clear();
        _lineOfSegment.Clear();
        DetectedLanguage = _detectedLanguage = null;
        Session.Elapsed = TranscriptLine.FormatTime(0);
        SetState(RecordingState.Starting);
        _recordingLive = LiveTranscription; // this page started it: never looked up
        try
        {
            var terms = VocabularyViewModel.ParseTerms(SessionTerms);
            var title = NormalizeTitle(Title);
            var request = new StartSessionRequest(
                Devices.MicDeviceId, Devices.SystemDeviceId, SelectedLanguage.Value, SelectedTemplate?.Id,
                terms.Count > 0 ? terms : null,
                LiveTranscription && SelectedTranslation.Value != _defaultTranslation ? SelectedTranslation.Value : null,
                title,
                LiveTranscription);
            var started = await _client.StartSessionAsync(request, _cancellation);
            _sentTitle = started.Title;
            Session.SessionId = started.Id;
            Session.Title = started.Title;
            SetState(RecordingState.Recording);
            if (NormalizeTitle(Title) != _sentTitle)
            {
                ScheduleTitleSave(); // edited while the engine was starting
            }
        }
        catch (Exception error) when (error is EngineApiException or EngineUnavailableException)
        {
            _notify(ErrorText(error));
            SetState(RecordingState.Idle);
        }
    }

    /// <summary>Enter in the title box: starts when idle (like Toggl); while recording, sends the title now.</summary>
    [RelayCommand]
    private async Task EnterAsync()
    {
        if (StartCommand.CanExecute(null))
        {
            await StartCommand.ExecuteAsync(null);
        }
        else if (IsRecording)
        {
            await SaveTitleNowAsync();
        }
    }

    [RelayCommand(CanExecute = nameof(CanStop))]
    private async Task StopAsync()
    {
        try
        {
            await SaveTitleNowAsync(); // a title still being typed belongs to this meeting
            await _client.StopSessionAsync(_cancellation);
            SetState(RecordingState.Idle); // the engine finishes the meeting in the background (phase 40)
        }
        catch (Exception error) when (error is EngineApiException or EngineUnavailableException)
        {
            _notify(ErrorText(error));
        }
    }

    /// <summary>The engine's form of a title: trimmed, whitespace runs as one space; blank = null.</summary>
    public static string? NormalizeTitle(string? title)
    {
        var words = (title ?? "").Split((char[]?)null, StringSplitOptions.RemoveEmptyEntries);
        return words.Length == 0 ? null : string.Join(' ', words);
    }

    partial void OnTitleChanged(string value)
    {
        if (IsRecording)
        {
            ScheduleTitleSave();
        }
    }

    private void ScheduleTitleSave()
    {
        _titleTyping?.Cancel();
        _titleTyping = new CancellationTokenSource();
        TitleSave = SaveTitleAfterTypingAsync(_titleTyping.Token);
    }

    private async Task SaveTitleAfterTypingAsync(CancellationToken typing)
    {
        try
        {
            await _titleDelay(TitleDebounce, typing);
        }
        catch (OperationCanceledException)
        {
            return; // more typing (or Enter / Stop) took over
        }

        await SaveTitleAsync();
    }

    /// <summary>Send the title at once, dropping a pending debounced update.</summary>
    private Task SaveTitleNowAsync()
    {
        _titleTyping?.Cancel();
        _titleTyping = null;
        TitleSave = SaveTitleAsync();
        return TitleSave;
    }

    /// <summary><c>PATCH /sessions/{id}</c> when the title differs from what the engine has.</summary>
    private async Task SaveTitleAsync()
    {
        var title = NormalizeTitle(Title);
        if (Session.SessionId is not { } sessionId || title == _sentTitle)
        {
            return;
        }

        try
        {
            var saved = await _client.UpdateSessionTitleAsync(sessionId, title, _cancellation);
            _sentTitle = saved.Title;
            if (Session.SessionId == sessionId)
            {
                Session.Title = saved.Title;
            }
        }
        catch (Exception error) when (error is EngineApiException or EngineUnavailableException)
        {
            _notify(ErrorText(error));
        }
    }

    private void OnSessionChanged(object? sender, PropertyChangedEventArgs args)
    {
        switch (args.PropertyName)
        {
            case nameof(RecordingSessionService.State):
                OnPropertyChanged(nameof(CanEditTitle));
                OnPropertyChanged(nameof(CanEditOptions));
                OnPropertyChanged(nameof(CanChooseTranslation));
                OnPropertyChanged(nameof(State));
                OnPropertyChanged(nameof(IsRecording));
                OnPropertyChanged(nameof(IsPaused));
                OnPropertyChanged(nameof(IsActivelyRecording));
                OnPropertyChanged(nameof(StatusText));
                OnPropertyChanged(nameof(PauseResumeText));
                NotifyTranscriptEmpty(); // the audio-only notice shows only while recording
                StartCommand.NotifyCanExecuteChanged();
                StopCommand.NotifyCanExecuteChanged();
                PauseResumeCommand.NotifyCanExecuteChanged();
                break;
            case nameof(RecordingSessionService.Elapsed):
                OnPropertyChanged(nameof(Elapsed));
                break;
        }
    }

    /// <summary>Append a transcript line and remember where its segment is (live translation, phase 29).</summary>
    private void AddLine(Segment segment)
    {
        _lineOfSegment[segment.SegmentId] = Segments.Count;
        Segments.Add(new TranscriptLine(
            TranscriptLine.FormatTime(segment.Start), segment.Label, segment.Text, segment.Channel)
        {
            Translation = segment.Translation?.Text,
        });
    }

    /// <summary>Show a live translation under the line of its segment (phase 29).</summary>
    private void OnTranslation(TranslationEvent translation)
    {
        if (_lineOfSegment.TryGetValue(translation.SegmentId, out var index) && index < Segments.Count)
        {
            Segments[index] = Segments[index] with { Translation = translation.Text };
        }
    }

    /// <summary>Change the option without remembering it; false when it did not change.</summary>
    private bool SetLiveTranscription(bool value)
    {
        if (!SetProperty(ref _liveTranscription, value, nameof(LiveTranscription)))
        {
            return false;
        }

        OnPropertyChanged(nameof(CanChooseTranslation));
        NotifyTranscriptEmpty();
        return true;
    }

    private void NotifyTranscriptEmpty()
    {
        OnPropertyChanged(nameof(IsTranscriptEmpty));
        OnPropertyChanged(nameof(IsAudioOnlyNotice));
        OnPropertyChanged(nameof(IsStartPromptVisible));
    }

    private static bool? ParseBool(string? text) => bool.TryParse(text, out var value) ? value : null;

    /// <summary><c>TRANSLATE_TO</c> becomes the picker's default (empty or unknown = off).</summary>
    private void ApplyDefaultTranslation(string? value)
    {
        var option = TranslationLanguages.FirstOrDefault(choice => choice.Value == value) ?? TranslationLanguages[0];
        _defaultTranslation = option.Value;
        SelectedTranslation = option;
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

    /// <summary>
    /// Whether a status belongs to the recording this page follows. Once the session id is known only
    /// that session counts (a stopped meeting's finalizing/done interleaves with a new recording);
    /// before it is known only <c>recording</c>/<c>paused</c> are adopted (a recording that started
    /// before the app connected).
    /// </summary>
    private bool Follows(StatusEvent status)
    {
        if (status.SessionId is not { } id)
        {
            return true;
        }

        return Session.SessionId is { } current
            ? id == current
            : status.Status is "recording" or "paused" && id != _lastStoppedId;
    }

    private void OnStatus(StatusEvent status)
    {
        if (!Follows(status))
        {
            return;
        }

        // The engine clock keeps running while paused (WAVs record silence); the display freezes
        // and continues from the engine clock on resume, matching the transcript timestamps.
        if (status.DurationSeconds is { } seconds && !(IsPaused && status.Status == "paused"))
        {
            Session.Elapsed = TranscriptLine.FormatTime(seconds);
        }

        if (status.Status is "recording" or "paused" && status.SessionId is { } sessionId)
        {
            Session.SessionId = sessionId; // also adopts a recording that started before the app connected
            if (_recordingLive is null)
            {
                _recordingLive = true; // started elsewhere: live until its session.json says otherwise
                RecordingModeLookup = ReadRecordingModeAsync(sessionId);
            }
        }

        SetState(status.Status switch
        {
            "recording" => RecordingState.Recording,
            "paused" => RecordingState.Paused,
            // finalizing, idle, done, interrupted: a finalizing meeting is processed in the background
            // (phase 40), also when it was stopped elsewhere (API, another client)
            _ => RecordingState.Idle,
        });
    }

    /// <summary>Show an adopted recording's own mode (<c>live_transcription</c> in its session.json).</summary>
    private async Task ReadRecordingModeAsync(string sessionId)
    {
        try
        {
            var detail = await _client.GetSessionAsync(sessionId, _cancellation);
            if (Session.SessionId == sessionId && _recordingLive is not null
                && detail.Metadata?.TryGetValue("live_transcription", out var live) == true
                && live.ValueKind == JsonValueKind.False)
            {
                _recordingLive = false;
                NotifyTranscriptEmpty();
            }
        }
        catch (Exception error) when (error is EngineApiException or EngineUnavailableException
                                          or OperationCanceledException)
        {
            // unknown: the notice stays as for a live recording
        }
    }

    private void SetState(RecordingState state)
    {
        if (state != RecordingState.Idle && _idle.Task.IsCompleted)
        {
            _idle = NewIdleSignal(completed: false);
        }

        var wasRecording = IsRecording;
        var hadSession = State is RecordingState.Recording or RecordingState.Paused or RecordingState.Finalizing;
        Session.State = state;
        Devices.IsEnabled = state == RecordingState.Idle;
        UpdateMeters(wasRecording);
        if (state == RecordingState.Idle)
        {
            _recordingLive = null;
            IsModelLoading = false;
            Partials.Clear();
            if (hadSession)
            {
                EndTitle(); // the next meeting starts untitled; this one is renamed from history
            }

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

    private void EndTitle()
    {
        _lastStoppedId = Session.SessionId ?? _lastStoppedId;
        _titleTyping?.Cancel();
        _titleTyping = null;
        _sentTitle = null;
        Session.SessionId = null;
        Session.Title = null;
        Title = ""; // not recording any more: nothing is sent
    }

    private void TickMeters()
    {
        MicMeter.Tick();
        SystemMeter.Tick();
    }

    private void RefreshDetectedLanguage()
    {
        var option = ConversationLanguages.FirstOrDefault(language => language.Value == _detectedLanguage);
        DetectedLanguage = option is null ? null : _localization.Format("DetectedLanguage", option.Label);
    }

    private static string? NonEmpty(string? text) => string.IsNullOrWhiteSpace(text) ? null : text;

    private string ErrorText(Exception error) =>
        error is EngineUnavailableException ? _localization["EngineUnavailable"] : error.Message;

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
