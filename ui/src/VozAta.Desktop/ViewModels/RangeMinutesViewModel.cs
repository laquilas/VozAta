using System.Globalization;
using CommunityToolkit.Mvvm.ComponentModel;
using CommunityToolkit.Mvvm.Input;
using VozAta.Client;
using VozAta.Desktop.Services;

namespace VozAta.Desktop.ViewModels;

/// <summary>Times typed as <c>hh:mm:ss</c>, <c>mm:ss</c> or seconds (phase 49).</summary>
public static class TimeText
{
    /// <summary>The inverse of <see cref="TranscriptLine.FormatTime"/>; minutes and seconds below 60.</summary>
    public static bool TryParse(string? text, out double seconds)
    {
        seconds = 0;
        if (string.IsNullOrWhiteSpace(text))
        {
            return false;
        }

        var parts = text.Trim().Split(':');
        if (parts.Length > 3)
        {
            return false;
        }

        double total = 0;
        for (var i = 0; i < parts.Length; i++)
        {
            if (!int.TryParse(parts[i], NumberStyles.None, CultureInfo.InvariantCulture, out var value)
                || (i > 0 && value >= 60))
            {
                return false;
            }

            total = (total * 60) + value;
        }

        seconds = total;
        return true;
    }
}

/// <summary>
/// "Minutes of a part" of a recorded meeting (phase 49): From / To typed, taken from the player
/// or from a transcript line, checked against the meeting's length, then written by the engine as
/// partial minutes (origin <c>range</c>).
/// </summary>
public sealed partial class RangeMinutesViewModel : ObservableObject
{
    /// <summary>The engine accepts a part ending up to one second after the recorded length.</summary>
    private const double LengthTolerance = 1.0;

    private static readonly HashSet<string> FailureCodes = ["empty_range", "partial_minutes_failed", "llm_unreachable"];

    private readonly IEngineClient _client;
    private readonly ILocalizationService _localization;
    private readonly string _sessionId;
    private readonly double _length;
    private readonly Func<double?> _playerPosition;
    private readonly Func<string?> _template;

    public RangeMinutesViewModel(
        IEngineClient client,
        ILocalizationService localization,
        string sessionId,
        double length,
        Func<double?> playerPosition,
        Func<string?> template)
    {
        _client = client;
        _localization = localization;
        _sessionId = sessionId;
        _length = length;
        _playerPosition = playerPosition;
        _template = template;
        To = TranscriptLine.FormatTime(Math.Ceiling(length));
    }

    [ObservableProperty]
    [NotifyPropertyChangedFor(nameof(ValidationError))]
    [NotifyCanExecuteChangedFor(nameof(GenerateCommand))]
    public partial string From { get; set; } = "00:00:00";

    [ObservableProperty]
    [NotifyPropertyChangedFor(nameof(ValidationError))]
    [NotifyCanExecuteChangedFor(nameof(GenerateCommand))]
    public partial string To { get; set; } = "";

    [ObservableProperty]
    [NotifyCanExecuteChangedFor(nameof(GenerateCommand))]
    public partial bool IsWriting { get; private set; }

    [ObservableProperty]
    public partial string? Error { get; private set; }

    /// <summary>Why the times cannot be used; null when they can.</summary>
    public string? ValidationError
    {
        get
        {
            if (!TimeText.TryParse(From, out var from) || !TimeText.TryParse(To, out var to))
            {
                return _localization["RangeInvalidTime"];
            }

            if (to <= from)
            {
                return _localization["RangeEndBeforeStart"];
            }

            return _length > 0 && to > _length + LengthTolerance
                ? _localization.Format("RangeBeyondEnd", TranscriptLine.FormatTime(Math.Ceiling(_length)))
                : null;
        }
    }

    /// <summary>Set From to a transcript line's start (its "Start here").</summary>
    public void StartAt(TranscriptLine line) => From = TranscriptLine.FormatTime(line.Start);

    /// <summary>Set To just after a transcript line's end (its "End here").</summary>
    public void EndAt(TranscriptLine line) => To = TranscriptLine.FormatTime(Math.Ceiling(Math.Max(line.End, line.Start + 1)));

    /// <summary>A <c>partial_minutes_ready</c> event: true when it is the part this asked for.</summary>
    public bool OnReady(PartialMinutesReadyEvent ready)
    {
        if (!IsWriting || ready.SessionId != _sessionId)
        {
            return false;
        }

        IsWriting = false;
        return true;
    }

    /// <summary>An <c>error</c> event: a failed request ends with the engine's message.</summary>
    public void OnError(string? sessionId, string code, string message)
    {
        if (IsWriting && sessionId == _sessionId && FailureCodes.Contains(code))
        {
            IsWriting = false;
            Error = message;
        }
    }

    private bool CanUsePlayer() => _playerPosition() is not null;

    [RelayCommand(CanExecute = nameof(CanUsePlayer))]
    private void FromPlayer() => From = TranscriptLine.FormatTime(_playerPosition() ?? 0);

    [RelayCommand(CanExecute = nameof(CanUsePlayer))]
    private void ToPlayer() => To = TranscriptLine.FormatTime(Math.Ceiling(_playerPosition() ?? 0));

    private bool CanGenerate() => !IsWriting && ValidationError is null;

    [RelayCommand(CanExecute = nameof(CanGenerate))]
    private async Task GenerateAsync()
    {
        if (!TimeText.TryParse(From, out var from) || !TimeText.TryParse(To, out var to))
        {
            return; // CanGenerate checked them already
        }

        Error = null;
        IsWriting = true;
        try
        {
            await _client.StartPartialMinutesAsync(_sessionId, from, to, _template());
        }
        catch (Exception error) when (error is EngineApiException or EngineUnavailableException)
        {
            IsWriting = false;
            Error = error is EngineUnavailableException ? _localization["EngineUnavailable"] : error.Message;
        }
    }

    /// <summary>The player appeared or went away: the "use the player position" buttons follow.</summary>
    public void PlayerChanged()
    {
        FromPlayerCommand.NotifyCanExecuteChanged();
        ToPlayerCommand.NotifyCanExecuteChanged();
    }
}
