using System.Net;
using VozAta.Client;
using VozAta.Desktop.Services;
using VozAta.Desktop.Tests.Fakes;
using VozAta.Desktop.ViewModels;

namespace VozAta.Desktop.Tests;

public sealed class AskViewModelTests
{
    private const string First = "20261015_202358";

    private readonly FakeEngineClient _client = new();
    private readonly LocalizationService _localization = new();

    private AskViewModel Create() => new(_client, _localization);

    private static AnswerChunkEvent Chunk(string text, string answerId = "answer-1") => new(null, answerId, text);

    private static AnswerDoneEvent Done(string answerId = "answer-1", string? error = null, params Citation[] citations) =>
        new(null, answerId, citations, error);

    private static async Task<AskViewModel> AskedAsync(AskViewModel ask, string question = "Who owns the migration?")
    {
        ask.Question = question;
        await ask.AskCommand.ExecuteAsync(null);
        return ask;
    }

    [Fact]
    public async Task Streamed_text_accumulates_in_order()
    {
        var ask = await AskedAsync(Create(), "  Who owns the migration?  ");

        Assert.True(ask.IsAsking);
        Assert.True(ask.IsThinking);
        ask.OnAnswerChunk(Chunk("Alice "));
        ask.OnAnswerChunk(Chunk("owns it "));
        ask.OnAnswerChunk(Chunk($"[{First}@00:01:23]."));

        Assert.Equal([("Who owns the migration?", (string?)null)], _client.Questions);
        Assert.Equal("Who owns the migration?", ask.AskedQuestion);
        Assert.Equal("", ask.Question);
        Assert.Equal($"Alice owns it [{First}@00:01:23].", ask.Answer);
        Assert.Equal("Alice owns it [00:01:23].", ask.DisplayAnswer);
        Assert.False(ask.IsThinking);
        Assert.True(ask.IsAsking);
    }

    [Fact]
    public async Task Done_lists_the_citations_and_allows_the_next_question()
    {
        var ask = await AskedAsync(Create());
        ask.OnAnswerChunk(Chunk("Alice."));

        ask.OnAnswerDone(Done(citations: new Citation(First, "mic-000004", 83.4)));

        Assert.False(ask.IsAsking);
        Assert.Null(ask.Error);
        var link = Assert.Single(ask.Citations);
        Assert.Equal(("00:01:23", "2026-10-15 20:23"), (link.Time, link.Date));
        Assert.Equal("00:01:23 · 2026-10-15 20:23", link.ToString());
        ask.Question = "next";
        Assert.True(ask.AskCommand.CanExecute(null));
    }

    [Fact]
    public async Task A_citation_opens_its_session_at_the_segment()
    {
        var ask = await AskedAsync(Create());
        var citation = new Citation(First, "mic-000004", 83.4);
        ask.OnAnswerDone(Done(citations: citation));
        var opened = new List<Citation>();
        ask.OpenCitation = picked =>
        {
            opened.Add(picked);
            return Task.CompletedTask;
        };

        await ask.OpenCommand.ExecuteAsync(ask.Citations[0]);
        await ask.OpenCommand.ExecuteAsync(null);

        Assert.Equal([citation], opened);
    }

    [Fact]
    public async Task Opening_without_a_handler_does_nothing()
    {
        var ask = await AskedAsync(Create());
        ask.OnAnswerDone(Done(citations: new Citation(First, "mic-000004", 83.4)));

        await ask.OpenCommand.ExecuteAsync(ask.Citations[0]);
    }

    [Fact]
    public async Task Concurrent_questions_are_blocked()
    {
        var ask = await AskedAsync(Create());

        ask.Question = "second question";

        Assert.False(ask.AskCommand.CanExecute(null));
        await ask.AskCommand.ExecuteAsync(null);
        Assert.Single(_client.Questions);
        Assert.Equal("second question", ask.Question);
    }

    [Theory]
    [InlineData("")]
    [InlineData("   ")]
    public void Blank_questions_cannot_be_asked(string question)
    {
        var ask = Create();

        ask.Question = question;

        Assert.False(ask.AskCommand.CanExecute(null));
    }

    [Fact]
    public void Too_long_questions_cannot_be_asked()
    {
        var ask = Create();

        ask.Question = new string('x', AskViewModel.MaxLength + 1);

        Assert.False(ask.AskCommand.CanExecute(null));
    }

    [Fact]
    public async Task Events_arriving_before_the_answer_id_are_replayed_in_order()
    {
        _client.AskGate = new TaskCompletionSource();
        var ask = Create();
        ask.Question = "q";
        var asking = ask.AskCommand.ExecuteAsync(null);

        ask.OnAnswerChunk(Chunk("one "));
        ask.OnAnswerChunk(Chunk("two"));
        ask.OnAnswerDone(Done());
        Assert.Equal("", ask.Answer);
        _client.AskGate.SetResult();
        await asking;

        Assert.Equal("one two", ask.Answer);
        Assert.False(ask.IsAsking);
    }

    [Fact]
    public async Task Events_of_other_answers_are_ignored()
    {
        var ask = await AskedAsync(Create());

        ask.OnAnswerChunk(Chunk("not mine", "answer-9"));
        ask.OnAnswerDone(Done("answer-9"));

        Assert.Equal("", ask.Answer);
        Assert.True(ask.IsAsking);
    }

    [Fact]
    public void Events_without_a_question_are_ignored()
    {
        var ask = Create();

        ask.OnAnswerChunk(Chunk("stray"));

        Assert.Equal("", ask.Answer);
    }

    [Fact]
    public async Task The_scope_is_the_selected_meeting_only_when_asked_for()
    {
        var ask = Create();
        Assert.False(ask.HasSelection);
        ask.SelectedOnly = true;
        Assert.Null(ask.Scope); // nothing selected: all meetings

        ask.SelectedSessionId = First;
        Assert.True(ask.HasSelection);
        Assert.Equal(First, ask.Scope);
        await AskedAsync(ask);
        ask.OnAnswerDone(Done());

        ask.SelectedOnly = false;
        Assert.Null(ask.Scope);
        await AskedAsync(ask);

        Assert.Equal([First, null], _client.Questions.Select(question => question.SessionId));
    }

    [Fact]
    public async Task A_rejected_question_shows_the_engine_message()
    {
        _client.AskError = new EngineApiException(HttpStatusCode.Conflict, "answer_in_progress", "Wait.");

        var ask = await AskedAsync(Create());

        Assert.Equal("Wait.", ask.Error);
        Assert.False(ask.IsAsking);
    }

    [Fact]
    public async Task An_unreachable_engine_shows_the_localized_message()
    {
        _client.AskError = new EngineUnavailableException("refused", new HttpRequestException("refused"));

        var ask = await AskedAsync(Create());

        Assert.Equal(_localization["EngineUnavailable"], ask.Error);
        Assert.False(ask.IsAsking);
    }

    [Fact]
    public async Task A_failed_answer_shows_its_error()
    {
        var ask = await AskedAsync(Create());

        ask.OnAnswerDone(Done(error: "Ollama offline"));

        Assert.Equal("Ollama offline", ask.Error);
        Assert.False(ask.IsAsking);
        Assert.Empty(ask.Citations);
    }

    [Fact]
    public async Task A_new_question_clears_the_previous_answer()
    {
        var ask = await AskedAsync(Create());
        ask.OnAnswerChunk(Chunk("old"));
        ask.OnAnswerDone(Done(error: "boom", citations: new Citation(First, "mic-000004", 83.4)));
        _client.NextAnswerId = "answer-2";

        await AskedAsync(ask, "new");

        Assert.Equal(("", null, "new"), (ask.Answer, ask.Error, ask.AskedQuestion));
        Assert.Empty(ask.Citations);
        ask.OnAnswerChunk(Chunk("late old chunk", "answer-1"));
        Assert.Equal("", ask.Answer);
    }

    [Fact]
    public async Task A_lost_connection_ends_the_answer_in_progress()
    {
        var ask = await AskedAsync(Create());

        ask.OnConnectionLost();

        Assert.Equal(_localization["AskConnectionLost"], ask.Error);
        Assert.False(ask.IsAsking);
        ask.OnAnswerChunk(Chunk("too late"));
        Assert.Equal("", ask.Answer);
    }

    [Fact]
    public async Task A_lost_connection_is_ignored_when_not_asking_or_still_posting()
    {
        var ask = Create();
        ask.OnConnectionLost();
        Assert.Null(ask.Error);

        _client.AskGate = new TaskCompletionSource();
        ask.Question = "q";
        var asking = ask.AskCommand.ExecuteAsync(null);
        ask.OnConnectionLost();
        _client.AskGate.SetResult();
        await asking;

        Assert.Null(ask.Error);
        Assert.True(ask.IsAsking);
    }

    [Fact]
    public async Task The_history_scopes_questions_to_the_selection_and_opens_citations()
    {
        for (var day = 3; day >= 1; day--)
        {
            var id = $"session_{day:000}";
            _client.Sessions.Add(new SessionSummary(id, "done", null, null, 60, "pt", true));
            _client.Details[id] = new SessionDetail(id, "done", null, null, 60, "pt", true, [], @"C:\r");
            _client.Transcripts[id] = new Transcript("raw",
            [
                new Segment("mic-000001", "mic", "mic", "Me", 1, 2, "Hello.", false, []),
                new Segment("mic-000002", "mic", "mic", "Me", 50, 52, "Alice owns it.", false, []),
            ]);
        }

        var history = new HistoryViewModel(_client, new FakeShell(), _localization, new FakeFileSaver());
        await history.LoadAsync();
        Assert.Null(history.Ask.SelectedSessionId);

        history.Selected = history.Rows[0];
        Assert.Equal("session_003", history.Ask.SelectedSessionId);

        await history.Ask.OpenCitation!(new Citation("session_002", "mic-000002", 50));
        await history.DetailLoading;

        Assert.Equal("session_002", history.Selected!.Id);
        Assert.Equal("session_002", history.Ask.SelectedSessionId);
        Assert.Equal("mic-000002", history.Detail!.FocusedLine!.SegmentId);
    }
}

public sealed class AskEventRoutingTests
{
    private readonly FakeEngineClient _client = new();
    private readonly FakeEngineEvents _events = new();

    private MainViewModel Create() => new(
        _client, _events, new FakeEngineProcess(), new ImmediateDispatcher(), new LocalizationService(), new FakeDialogs(),
        new FakePreferences(), new FakeClock(), new FakeTimer(), new FakeShell(), new FakeFileSaver());

    private async Task SendAsync(MainViewModel viewModel, EngineEvent engineEvent)
    {
        var before = viewModel.HandledEvents;
        _events.Send(engineEvent);
        for (var i = 0; i < 200 && viewModel.HandledEvents == before; i++)
        {
            await Task.Delay(5);
        }

        Assert.True(viewModel.HandledEvents > before, $"{engineEvent} was not handled");
    }

    private async Task<(MainViewModel ViewModel, AskViewModel Ask)> AskingAsync()
    {
        var viewModel = Create();
        await viewModel.InitializeAsync();
        await SendAsync(viewModel, new ConnectionChangedEvent(true));
        var ask = viewModel.History.Ask;
        ask.Question = "q";
        await ask.AskCommand.ExecuteAsync(null);
        return (viewModel, ask);
    }

    [Fact]
    public async Task Answer_events_reach_the_history_ask_panel()
    {
        var (viewModel, ask) = await AskingAsync();

        await SendAsync(viewModel, new AnswerChunkEvent(null, "answer-1", "Alice"));
        await SendAsync(viewModel, new AnswerDoneEvent(null, "answer-1", [new Citation("s1", "mic-000001", 1)], null));

        Assert.Equal("Alice", ask.Answer);
        Assert.Single(ask.Citations);
        Assert.False(ask.IsAsking);
    }

    [Fact]
    public async Task A_dropped_connection_ends_the_answer_in_progress()
    {
        var (viewModel, ask) = await AskingAsync();

        await SendAsync(viewModel, new ConnectionChangedEvent(false));

        Assert.False(ask.IsAsking);
        Assert.NotNull(ask.Error);
    }
}
