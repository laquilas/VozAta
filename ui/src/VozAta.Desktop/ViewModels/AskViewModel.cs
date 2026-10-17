using System.Collections.ObjectModel;
using System.Text.RegularExpressions;
using CommunityToolkit.Mvvm.ComponentModel;
using CommunityToolkit.Mvvm.Input;
using VozAta.Client;
using VozAta.Desktop.Services;

namespace VozAta.Desktop.ViewModels;

/// <summary>A cited transcript segment the user can open: time and meeting date.</summary>
public sealed record CitationLink(Citation Citation, string Time, string Date)
{
    /// <summary>What the link shows and screen readers announce.</summary>
    public override string ToString() => $"{Time} · {Date}";
}

/// <summary>
/// Ask the meeting (phase 24): one question at a time about the selected meeting or all of them.
/// The answer text accumulates from <c>answer_chunk</c> events; <c>answer_done</c> adds the
/// citations, which open the session at the cited segment.
/// </summary>
public sealed partial class AskViewModel(IEngineClient client, ILocalizationService localization) : ObservableObject
{
    public const int MaxLength = 2000;

    private readonly List<EngineEvent> _early = [];

    private string? _answerId;

    private bool _awaitingId;

    public ObservableCollection<CitationLink> Citations { get; } = [];

    [ObservableProperty]
    [NotifyCanExecuteChangedFor(nameof(AskCommand))]
    public partial string Question { get; set; } = "";

    /// <summary>The question being (or last) answered.</summary>
    [ObservableProperty]
    public partial string? AskedQuestion { get; private set; }

    /// <summary>The answer as streamed, with citations as <c>[session_id@hh:mm:ss]</c>.</summary>
    [ObservableProperty]
    [NotifyPropertyChangedFor(nameof(DisplayAnswer), nameof(IsThinking))]
    public partial string Answer { get; private set; } = "";

    [ObservableProperty]
    [NotifyCanExecuteChangedFor(nameof(AskCommand))]
    [NotifyPropertyChangedFor(nameof(IsThinking))]
    public partial bool IsAsking { get; private set; }

    [ObservableProperty]
    public partial string? Error { get; private set; }

    /// <summary>The meeting selected in the history (null: none).</summary>
    [ObservableProperty]
    [NotifyPropertyChangedFor(nameof(HasSelection), nameof(Scope))]
    public partial string? SelectedSessionId { get; set; }

    /// <summary>Ask about the selected meeting only (otherwise: all meetings).</summary>
    [ObservableProperty]
    [NotifyPropertyChangedFor(nameof(Scope))]
    public partial bool SelectedOnly { get; set; }

    /// <summary>Called with the citation the user picked (the history opens the session there).</summary>
    public Func<Citation, Task>? OpenCitation { get; set; }

    public bool HasSelection => SelectedSessionId is not null;

    /// <summary>The session the next question is about; null for all sessions.</summary>
    public string? Scope => SelectedOnly ? SelectedSessionId : null;

    /// <summary>Waiting for the first words of the answer.</summary>
    public bool IsThinking => IsAsking && Answer.Length == 0;

    /// <summary>The answer with citations shortened to their time (the links name the meeting).</summary>
    public string DisplayAnswer => SessionPrefix().Replace(Answer, "");

    [RelayCommand(CanExecute = nameof(CanAsk))]
    private async Task AskAsync()
    {
        var question = Question.Trim();
        if (!CanAsk())
        {
            return;
        }

        IsAsking = true;
        AskedQuestion = question;
        Answer = "";
        Error = null;
        Citations.Clear();
        _answerId = null;
        _awaitingId = true;
        try
        {
            var accepted = await client.AskAsync(question, Scope);
            _answerId = accepted.AnswerId;
            Question = "";
        }
        catch (Exception error) when (error is EngineApiException or EngineUnavailableException)
        {
            Error = error is EngineUnavailableException ? localization["EngineUnavailable"] : error.Message;
            IsAsking = false;
        }
        finally
        {
            _awaitingId = false;
        }

        var early = _early.ToList();
        _early.Clear();
        foreach (var engineEvent in early) // events that arrived before the answer id
        {
            Handle(engineEvent);
        }
    }

    private bool CanAsk() => !IsAsking && Question.Trim().Length is > 0 and <= MaxLength;

    [RelayCommand]
    private Task OpenAsync(CitationLink? link) =>
        link is not null && OpenCitation is not null ? OpenCitation(link.Citation) : Task.CompletedTask;

    public void OnAnswerChunk(AnswerChunkEvent chunk) => Handle(chunk);

    public void OnAnswerDone(AnswerDoneEvent done) => Handle(done);

    /// <summary>The event connection dropped: an answer in progress will not finish.</summary>
    public void OnConnectionLost()
    {
        if (!IsAsking || _awaitingId)
        {
            return;
        }

        _answerId = null;
        Error = localization["AskConnectionLost"];
        IsAsking = false;
    }

    private void Handle(EngineEvent engineEvent)
    {
        var answerId = engineEvent switch
        {
            AnswerChunkEvent chunk => chunk.AnswerId,
            AnswerDoneEvent done => done.AnswerId,
            _ => null,
        };
        if (_awaitingId)
        {
            _early.Add(engineEvent);
            return;
        }

        if (answerId is null || answerId != _answerId)
        {
            return; // another window's question, or an answer we stopped waiting for
        }

        switch (engineEvent)
        {
            case AnswerChunkEvent chunk:
                Answer += chunk.Text;
                break;
            case AnswerDoneEvent done:
                foreach (var citation in done.Citations)
                {
                    Citations.Add(new CitationLink(
                        citation, TranscriptLine.FormatTime(citation.Start), SearchViewModel.FormatSessionDate(citation.SessionId)));
                }

                Error = done.Error;
                _answerId = null;
                IsAsking = false;
                break;
        }
    }

    [GeneratedRegex(@"\d{8}_\d{6}(?:_[1-9]\d*)?\s*@\s*")]
    private static partial Regex SessionPrefix();
}
