using System.Collections.ObjectModel;
using System.Globalization;
using CommunityToolkit.Mvvm.ComponentModel;
using VozAta.Client;
using VozAta.Desktop.Services;

namespace VozAta.Desktop.ViewModels;

/// <summary>One line of a meeting's request history: "12:34 · Comando de voz · Gerar a ata · Pronta".</summary>
public sealed partial class RequestRow(RequestEntry entry, ILocalizationService localization) : ObservableObject
{
    public RequestEntry Entry { get; private set; } = entry;

    /// <summary>The meeting second it was asked at while recording, else the local clock time.</summary>
    public string Time => Entry.At is { } at
        ? TranscriptLine.FormatTime(at)
        : DateTimeOffset.TryParse(Entry.CreatedAt, CultureInfo.InvariantCulture, out var created)
            ? created.ToLocalTime().ToString("HH:mm", CultureInfo.InvariantCulture)
            : "";

    /// <summary>"Comando de voz · Ata até agora".</summary>
    public string What => $"{localization[$"RequestSource_{Entry.Source}"]} · {localization[$"RequestKind_{Entry.Kind}"]}";

    /// <summary>The phrase heard or the question; empty for a button.</summary>
    public string Text => Entry.Text;

    public bool HasText => Entry.Text.Length > 0;

    /// <summary>"Pronta", "Falhou: o modelo de linguagem não respondeu", "Já estava em andamento".</summary>
    public string StatusText => Entry.Message is { } code && Entry.Status is "failed" or "ignored"
        ? $"{localization[$"RequestStatus_{Entry.Status}"]}: {Reason(code)}"
        : localization[$"RequestStatus_{Entry.Status}"];

    public bool IsOk => Entry.Status == "done";

    public bool IsBusy => Entry.Status is "recognized" or "running" or "ignored";

    public bool IsFailed => Entry.Status == "failed";

    public void Update(RequestEntry entry)
    {
        Entry = entry;
        RefreshTexts();
    }

    public void RefreshTexts()
    {
        OnPropertyChanged(nameof(Time));
        OnPropertyChanged(nameof(What));
        OnPropertyChanged(nameof(Text));
        OnPropertyChanged(nameof(HasText));
        OnPropertyChanged(nameof(StatusText));
        OnPropertyChanged(nameof(IsOk));
        OnPropertyChanged(nameof(IsBusy));
        OnPropertyChanged(nameof(IsFailed));
    }

    private string Reason(string code) =>
        RequestHistoryViewModel.KnownReasons.Contains(code) ? localization[$"RequestReason_{code}"] : code;
}

/// <summary>
/// The request history of one meeting (phase 59), newest first: the meeting page's Histórico tab
/// (a fixed meeting) and the Recorder's list (it follows the meeting being recorded). Live through
/// <c>request_updated</c> events of that meeting.
/// </summary>
public sealed partial class RequestHistoryViewModel(
    IEngineClient client, ILocalizationService localization, string? sessionId = null) : ObservableObject
{
    /// <summary>Codes with their own wording (<c>RequestReason_{code}</c>); others show as they are.</summary>
    internal static readonly HashSet<string> KnownReasons =
    [
        "voice_command_busy", "voice_command_repeated", "voice_command_unavailable", "empty_range",
        "empty_transcript", "llm_unreachable", "partial_minutes_failed", "partial_minutes_in_progress",
        "answer_failed", "answer_in_progress", "minutes_failed", "action_items_failed", "session_still_active",
    ];

    private string? _sessionId = sessionId;

    public ObservableCollection<RequestRow> Rows { get; } = [];

    [ObservableProperty]
    public partial bool HasRows { get; private set; }

    [ObservableProperty]
    public partial string? Error { get; private set; }

    /// <summary>Read the meeting's history again.</summary>
    public async Task LoadAsync(CancellationToken cancellationToken = default)
    {
        if (_sessionId is not { } id)
        {
            return;
        }

        try
        {
            var list = await client.GetRequestsAsync(id, cancellationToken);
            if (id != _sessionId)
            {
                return; // another meeting was followed meanwhile
            }

            Rows.Clear();
            foreach (var entry in list.Items.Reverse())
            {
                Rows.Add(new RequestRow(entry, localization));
            }

            Error = null;
        }
        catch (Exception error) when (error is EngineApiException or EngineUnavailableException)
        {
            Error = error is EngineUnavailableException ? localization["EngineUnavailable"] : error.Message;
        }

        HasRows = Rows.Count > 0;
    }

    /// <summary>The Recorder follows the meeting being recorded (null: none).</summary>
    public Task FollowAsync(string? followed)
    {
        if (followed == _sessionId)
        {
            return Task.CompletedTask;
        }

        _sessionId = followed;
        Rows.Clear();
        HasRows = false;
        return LoadAsync();
    }

    /// <summary>A <c>request_updated</c> event: update its row, or add it on top.</summary>
    public void OnRequest(RequestUpdatedEvent updated)
    {
        if (updated.SessionId is null || updated.SessionId != _sessionId)
        {
            return;
        }

        if (Rows.FirstOrDefault(row => row.Entry.Id == updated.Request.Id) is { } row)
        {
            row.Update(updated.Request);
        }
        else
        {
            Rows.Insert(0, new RequestRow(updated.Request, localization));
        }

        HasRows = true;
    }

    public void RefreshTexts()
    {
        foreach (var row in Rows)
        {
            row.RefreshTexts();
        }
    }
}
