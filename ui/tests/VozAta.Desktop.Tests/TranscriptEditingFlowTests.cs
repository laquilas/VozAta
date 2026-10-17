using VozAta.Client;
using VozAta.Desktop.Services;
using VozAta.Desktop.Tests.Fakes;
using VozAta.Desktop.ViewModels;

namespace VozAta.Desktop.Tests;

/// <summary>Phase 21 inside the session detail and the history list: highlight, save, guard.</summary>
public sealed class TranscriptEditingFlowTests
{
    private const string First = "20261016_090000";
    private const string Second = "20261015_090000";

    private readonly FakeEngineClient _client = new();
    private readonly LocalizationService _localization = new();
    private readonly FakeDialogs _dialogs = new();

    public TranscriptEditingFlowTests()
    {
        foreach (var id in new[] { First, Second })
        {
            _client.Sessions.Add(Summary(id));
            _client.Details[id] = new SessionDetail(id, "done", null, null, 70, "en", true, [], @"C:\r\" + id);
            _client.Transcripts[id] = new Transcript("raw",
            [
                new Segment("mic-000001", "mic", "mic", "Me", 1, 2, "We ship on Friday.", false,
                    [new Word(" We", 1, 1.2, 0.9), new Word(" ship", 1.2, 1.5, 0.2), new Word(" on", 1.5, 1.6, 0.9), new Word(" Friday.", 1.6, 2, 0.9)]),
                new Segment("system-000001", "system", "system", "Others", 65, 66, "Hi.", false, []),
            ]);
        }
    }

    private static SessionSummary Summary(string id, string status = "done") =>
        new(id, status, new DateTimeOffset(2026, 10, 16, 9, 0, 0, TimeSpan.Zero), null, 70, "en", true);

    private SessionDetailViewModel Detail(string status = "done") =>
        new(_client, new FakeShell(), _localization, new FakeFileSaver(), Summary(First, status), dialogs: _dialogs);

    private HistoryViewModel History() =>
        new(_client, new FakeShell(), _localization, new FakeFileSaver(), dialogs: _dialogs);

    [Fact]
    public async Task Read_mode_highlights_low_confidence_words()
    {
        var detail = Detail();

        await detail.LoadAsync();

        Assert.True(detail.HasLowConfidence);
        Assert.Equal(
            [new TextPart("[00:00:01] Me: "), new TextPart("We "), new TextPart("ship", true), new TextPart(" on Friday.")],
            detail.Lines[0].DisplayParts);
        Assert.Null(detail.Lines[1].LowConfidenceParts);
        Assert.Equal([new TextPart("[00:01:05] Others: "), new TextPart("Hi.")], detail.Lines[1].DisplayParts);
    }

    [Fact]
    public async Task The_engine_threshold_decides_what_is_highlighted()
    {
        _client.SettingValues["LOW_CONFIDENCE_THRESHOLD"] = 0.1;
        var detail = Detail();

        await detail.LoadAsync();

        Assert.False(detail.HasLowConfidence);
    }

    [Fact]
    public async Task Saving_reloads_the_lines_with_the_correction_and_suggests_regenerating()
    {
        var detail = Detail();
        await detail.LoadAsync();
        detail.Editor.EditCommand.Execute(null);
        detail.Editor.Segments[0].Text = "We ship on Thursday.";

        await detail.Editor.SaveCommand.ExecuteAsync(null);

        Assert.Equal("We ship on Thursday.", detail.Lines[0].Text);
        Assert.Null(detail.Lines[0].LowConfidenceParts); // edited: no word confidence any more
        Assert.True(detail.Editor.HasEdits);
        Assert.True(detail.Editor.SuggestRegenerate);

        await detail.RegenerateMinutesCommand.ExecuteAsync(null);

        Assert.False(detail.Editor.SuggestRegenerate);
        Assert.Equal([First], _client.Regenerated);
    }

    [Fact]
    public void A_live_session_cannot_be_edited()
    {
        var detail = Detail("recording");

        Assert.True(detail.Editor.IsLive);
        Assert.False(detail.Editor.EditCommand.CanExecute(null));
    }

    private async Task<HistoryViewModel> EditingFirstAsync()
    {
        var history = History();
        await history.LoadAsync();
        history.Selected = history.Rows[0];
        await history.DetailLoading;
        history.Detail!.Editor.EditCommand.Execute(null);
        history.Detail.Editor.Segments[0].Text = "Changed.";
        return history;
    }

    [Fact]
    public async Task Selecting_another_session_with_unsaved_edits_asks_and_stays_on_no()
    {
        var history = await EditingFirstAsync();
        var editing = history.Detail;
        _dialogs.Answer = false;

        history.Selected = history.Rows[1];
        await history.SelectionGuard;

        Assert.Equal([_localization["ConfirmDiscardEditsTitle"]], _dialogs.Asked);
        Assert.Same(editing, history.Detail);
        Assert.Equal(First, history.Selected?.Id);
        Assert.True(editing!.Editor.IsDirty);
    }

    [Fact]
    public async Task Selecting_another_session_with_unsaved_edits_opens_it_on_yes()
    {
        var history = await EditingFirstAsync();

        history.Selected = history.Rows[1];
        await history.SelectionGuard;
        await history.DetailLoading;

        Assert.Single(_dialogs.Asked);
        Assert.Equal(Second, history.Detail?.Id);
        Assert.Empty(_client.TranscriptUpdates);
    }

    [Fact]
    public async Task A_cleared_selection_keeps_the_session_being_edited()
    {
        var history = await EditingFirstAsync();
        var editing = history.Detail;

        history.Selected = null;

        Assert.Same(editing, history.Detail);
        Assert.Empty(_dialogs.Asked);
    }

    [Fact]
    public async Task Without_unsaved_edits_selection_changes_freely()
    {
        var history = History();
        await history.LoadAsync();
        history.Selected = history.Rows[0];
        await history.DetailLoading;

        history.Selected = history.Rows[1];

        Assert.Equal(Second, history.Detail?.Id);
        Assert.Empty(_dialogs.Asked);
        Assert.True(await history.ConfirmLeaveAsync());
    }

    [Fact]
    public async Task Leaving_with_no_session_open_is_allowed()
    {
        Assert.True(await History().ConfirmLeaveAsync());
    }

    [Fact]
    public async Task A_search_hit_in_another_session_waits_for_the_guard()
    {
        var history = await EditingFirstAsync();
        _dialogs.Answer = false;

        await history.OpenHitAsync(new SearchHit(Second, "system-000001", 65, "system", "Others", "Hi"));

        Assert.Equal(First, history.Detail?.Id);
        Assert.Null(history.Detail?.FocusedLine);
    }
}
