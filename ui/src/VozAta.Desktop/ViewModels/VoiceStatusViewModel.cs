using System.ComponentModel;
using CommunityToolkit.Mvvm.ComponentModel;
using CommunityToolkit.Mvvm.Input;
using VozAta.Client;
using VozAta.Desktop.Services;

namespace VozAta.Desktop.ViewModels;

/// <summary>The colour of the sidebar's voice status (phase 59).</summary>
public enum VoiceStatusState
{
    /// <summary>Gray: listening, nothing asked.</summary>
    Idle,

    /// <summary>Green: the command was understood ("Gerar a ata").</summary>
    Recognized,

    /// <summary>Yellow: being processed ("Gerando a ata…"), or a repeat of one being processed.</summary>
    Processing,

    /// <summary>Green: the result is ready ("Ata pronta (até 12:34)").</summary>
    Done,

    /// <summary>Red: it failed, with the reason.</summary>
    Failed,
}

/// <summary>
/// The sidebar line that says what became of a voice command while recording (phase 59): gray idle,
/// green "Gerar a ata" for <see cref="RecognizedHold"/>, yellow "Gerando a ata…", green "Ata pronta
/// (até mm:ss)" for <see cref="DoneHold"/>, red with the reason for <see cref="FailedHold"/>, then gray
/// again. Driven by the <c>request_updated</c> entries of the meeting being recorded whose source is
/// <c>voice</c>. A recognized command plays a short sound when <see cref="IsSoundOn"/>.
/// </summary>
public sealed partial class VoiceStatusViewModel : ObservableObject
{
    public static readonly TimeSpan RecognizedHold = TimeSpan.FromSeconds(1.5);
    public static readonly TimeSpan DoneHold = TimeSpan.FromSeconds(5);
    public static readonly TimeSpan FailedHold = TimeSpan.FromSeconds(8);
    public static readonly TimeSpan RepeatHold = TimeSpan.FromSeconds(4);

    /// <summary>Failure codes with their own short reason (<c>VoiceStatus_Error_{code}</c>).</summary>
    private static readonly HashSet<string> KnownErrors =
    [
        "voice_command_busy", "voice_command_unavailable", "empty_range", "llm_unreachable",
        "partial_minutes_failed", "answer_failed",
    ];

    private readonly ILocalizationService _localization;
    private readonly RecordingSessionService _session;
    private readonly Func<TimeSpan, CancellationToken, Task> _delay;
    private readonly ISoundPlayer _sound;
    private readonly IUiPreferences _preferences;
    private RequestEntry? _request; // the one shown
    private RequestEntry? _pending; // arrived while the green "recognized" is held
    private RequestEntry? _active; // the one being processed, shown again after a repeat
    private bool _holding;
    private int _version;

    public VoiceStatusViewModel(
        ILocalizationService localization,
        RecordingSessionService session,
        IUiPreferences preferences,
        ISoundPlayer? sound = null,
        Func<TimeSpan, CancellationToken, Task>? delay = null)
    {
        _localization = localization;
        _session = session;
        _preferences = preferences;
        _sound = sound ?? new SilentSoundPlayer();
        _delay = delay ?? Task.Delay;
        _isSoundOn = preferences.Load().VoiceCommandSound;
        session.PropertyChanged += OnSessionChanged;
    }

    /// <summary>Raised by <see cref="OpenCommand"/>: show this finished request's result.</summary>
    public event Action<RequestEntry>? Opened;

    /// <summary>Only while recording: commands are heard only then.</summary>
    public bool IsVisible => _session.IsRecording;

    [ObservableProperty]
    [NotifyPropertyChangedFor(nameof(IsIdle), nameof(IsOk), nameof(IsBusy), nameof(IsFailed), nameof(Text), nameof(ToolTipText))]
    [NotifyCanExecuteChangedFor(nameof(OpenCommand))]
    public partial VoiceStatusState State { get; private set; }

    public bool IsIdle => State == VoiceStatusState.Idle;

    public bool IsOk => State is VoiceStatusState.Recognized or VoiceStatusState.Done;

    public bool IsBusy => State == VoiceStatusState.Processing;

    public bool IsFailed => State == VoiceStatusState.Failed;

    /// <summary>"Gerar a ata", "Gerando a ata…", "Ata pronta (até 12:34)", "Falhou: …".</summary>
    public string Text => State switch
    {
        VoiceStatusState.Idle => _localization["VoiceStatus_Idle"],
        _ when _request is null => _localization["VoiceStatus_Idle"],
        VoiceStatusState.Recognized => RecognizedText(_request),
        VoiceStatusState.Processing when _request.Status == "ignored" => _localization[IsAsk(_request) ? "VoiceStatus_RepeatAsk" : "VoiceStatus_RepeatMinutes"],
        VoiceStatusState.Processing => _localization[IsAsk(_request) ? "VoiceStatus_Answering" : "VoiceStatus_Writing"],
        VoiceStatusState.Done when IsAsk(_request) => _localization["VoiceStatus_AnswerReady"],
        VoiceStatusState.Done => _request.At is { } at
            ? _localization.Format("VoiceStatus_MinutesReadyUpTo", TranscriptLine.FormatTime(at))
            : _localization["VoiceStatus_MinutesReady"],
        _ => _localization.Format("VoiceStatus_Failed", FailureReason(_request.Message)),
    };

    /// <summary>The idle hint, or the line plus "click to open" when a result is ready.</summary>
    public string ToolTipText => State switch
    {
        VoiceStatusState.Idle => _localization["VoiceStatus_IdleHint"],
        VoiceStatusState.Done => $"{Text}\n{_localization["VoiceStatus_ClickToOpen"]}",
        _ => Text,
    };

    private bool _isSoundOn;

    /// <summary>A short sound when a command is understood (Config; <c>ui.json</c>).</summary>
    public bool IsSoundOn
    {
        get => _isSoundOn;
        set
        {
            if (SetProperty(ref _isSoundOn, value))
            {
                _preferences.Save(_preferences.Load() with { VoiceCommandSound = value });
            }
        }
    }

    /// <summary>The last hold that was started (tests await it).</summary>
    public Task Hold { get; private set; } = Task.CompletedTask;

    /// <summary>A <c>request_updated</c> event.</summary>
    public void OnRequest(RequestUpdatedEvent updated)
    {
        var request = updated.Request;
        if (request.Source != "voice" || updated.SessionId is null || updated.SessionId != _session.SessionId)
        {
            return;
        }

        if (request.Status == "recognized")
        {
            if (IsSoundOn)
            {
                _sound.PlayChime();
            }

            _pending = null;
            Show(request, VoiceStatusState.Recognized);
            _holding = true;
            Hold = HoldThenAsync(RecognizedHold, ++_version, ReleaseRecognized);
            return;
        }

        if (_holding && request.Id == _request?.Id)
        {
            _pending = request; // shown once the green "understood" was seen
            return;
        }

        Apply(request);
    }

    public void RefreshTexts()
    {
        OnPropertyChanged(nameof(Text));
        OnPropertyChanged(nameof(ToolTipText));
    }

    private bool CanOpen() => State == VoiceStatusState.Done;

    [RelayCommand(CanExecute = nameof(CanOpen))]
    private void Open()
    {
        if (_request is { } request)
        {
            Opened?.Invoke(request);
        }
    }

    private void Apply(RequestEntry request)
    {
        switch (request.Status)
        {
            case "running":
                _active = request;
                Show(request, VoiceStatusState.Processing);
                ++_version;
                break;
            case "ignored": // a repeat: say "already on it", then back to the one being processed
                Show(request, VoiceStatusState.Processing);
                Hold = HoldThenAsync(RepeatHold, ++_version, ShowActive);
                break;
            case "done":
                ClearActive(request);
                Show(request, VoiceStatusState.Done);
                Hold = HoldThenAsync(DoneHold, ++_version, Reset);
                break;
            case "failed":
                ClearActive(request);
                Show(request, VoiceStatusState.Failed);
                Hold = HoldThenAsync(FailedHold, ++_version, Reset);
                break;
        }
    }

    private void ReleaseRecognized()
    {
        _holding = false;
        if (_pending is { } pending)
        {
            _pending = null;
            Apply(pending);
        }
    }

    private void ShowActive()
    {
        if (_active is { } active)
        {
            Show(active, VoiceStatusState.Processing);
        }
        else
        {
            Reset();
        }
    }

    private void ClearActive(RequestEntry finished)
    {
        if (_active?.Id == finished.Id)
        {
            _active = null;
        }
    }

    private void Reset()
    {
        _request = null;
        State = VoiceStatusState.Idle;
        RefreshTexts();
    }

    private void Show(RequestEntry request, VoiceStatusState state)
    {
        _request = request;
        State = state;
        RefreshTexts();
    }

    private async Task HoldThenAsync(TimeSpan hold, int version, Action then)
    {
        await _delay(hold, CancellationToken.None);
        if (version == _version)
        {
            then();
        }
        else if (then == ReleaseRecognized)
        {
            _holding = false; // a newer command took over
        }
    }

    private void OnSessionChanged(object? sender, PropertyChangedEventArgs args)
    {
        if (args.PropertyName != nameof(RecordingSessionService.State))
        {
            return;
        }

        if (!_session.IsRecording)
        {
            ++_version;
            _holding = false;
            _pending = _active = null;
            Reset();
        }

        OnPropertyChanged(nameof(IsVisible));
    }

    private string RecognizedText(RequestEntry request) =>
        IsAsk(request) && request.Text.Length > 0 ? request.Text : _localization["VoiceStatus_Minutes"];

    private string FailureReason(string? code) =>
        _localization[code is not null && KnownErrors.Contains(code) ? $"VoiceStatus_Error_{code}" : "VoiceStatus_Error_other"];

    private static bool IsAsk(RequestEntry request) => request.Kind == "ask";
}
