using System.Net;
using VozAta.Client;
using VozAta.Desktop.Services;
using VozAta.Desktop.Tests.Fakes;
using VozAta.Desktop.ViewModels;

namespace VozAta.Desktop.Tests;

public sealed class TranscriptEditorViewModelTests
{
    private const string Id = "20261016_090000";

    private static readonly Word[] Words =
    [
        new(" We", 1, 1.2, 0.9),
        new(" ship", 1.2, 1.5, 0.3),
        new(" on", 1.5, 1.6, 0.95),
        new(" Friday.", 1.6, 2, 0.4),
    ];

    private readonly FakeEngineClient _client = new();
    private readonly LocalizationService _localization = new();
    private readonly FakeDialogs _dialogs = new();
    private int _reloads;

    public TranscriptEditorViewModelTests()
    {
        _client.Transcripts[Id] = Original;
    }

    private static Transcript Original => new("raw",
    [
        new Segment("mic-000001", "mic", "mic", "Me", 1, 2, "We ship on Friday.", false, Words),
        new Segment("system-000001", "system", "system", "Others", 65, 66, "Hi.", false, []),
    ]);

    private TranscriptEditorViewModel Create(IDialogService? dialogs = null)
    {
        TranscriptEditorViewModel? editor = null;
        editor = new TranscriptEditorViewModel(_client, _localization, dialogs ?? _dialogs, Id)
        {
            Reload = async () =>
            {
                _reloads++;
                editor!.Load(await _client.GetTranscriptAsync(Id));
            },
        };
        editor.Load(_client.Transcripts[Id]);
        return editor;
    }

    // Highlight computation

    [Fact]
    public void Low_confidence_words_are_split_out_in_order()
    {
        var parts = LowConfidence.Split("We ship on Friday.", Words, 0.5);

        Assert.Equal(
            [new TextPart("We "), new TextPart("ship", true), new TextPart(" on "), new TextPart("Friday.", true)],
            parts);
    }

    [Fact]
    public void Nothing_is_highlighted_when_every_word_is_confident()
    {
        Assert.Null(LowConfidence.Split("We ship on Friday.", Words, 0.25));
        Assert.Null(LowConfidence.Split("Hi.", [], 0.5));
    }

    [Fact]
    public void The_threshold_is_exclusive_and_trailing_text_is_kept()
    {
        Word[] words = [new("We", 0, 1, 0.5), new("ship", 1, 2, 0.49)];

        var parts = LowConfidence.Split("We ship it", words, 0.5);

        Assert.Equal([new TextPart("We "), new TextPart("ship", true), new TextPart(" it")], parts);
    }

    [Fact]
    public void Words_missing_from_the_text_are_skipped()
    {
        Word[] words = [new("gone", 0, 1, 0.1), new(" ", 1, 1, 0.1), new("there", 1, 2, 0.1)];

        var parts = LowConfidence.Split("still there", words, 0.5);

        Assert.Equal([new TextPart("still "), new TextPart("there", true)], parts);
    }

    [Fact]
    public void Edited_segments_are_never_highlighted()
    {
        var editor = Create();
        var segment = Original.Segments[0];

        Assert.NotNull(editor.Highlight(segment));
        Assert.Null(editor.Highlight(segment with { Edited = true }));
    }

    [Fact]
    public async Task The_threshold_comes_from_the_engine_settings()
    {
        _client.SettingValues["LOW_CONFIDENCE_THRESHOLD"] = 0.35;
        var editor = Create();

        await editor.LoadThresholdAsync();

        Assert.Equal(0.35, editor.Threshold);
        Assert.Equal([new TextPart("We "), new TextPart("ship", true), new TextPart(" on Friday.")],
            editor.Highlight(Original.Segments[0]));
    }

    [Fact]
    public async Task The_default_threshold_is_kept_when_settings_fail_or_lack_the_key()
    {
        var editor = Create();
        await editor.LoadThresholdAsync();
        Assert.Equal(LowConfidence.DefaultThreshold, editor.Threshold);

        _client.SettingsError = new EngineUnavailableException("refused", new HttpRequestException());
        await editor.LoadThresholdAsync();
        Assert.Equal(LowConfidence.DefaultThreshold, editor.Threshold);
    }

    // Dirty tracking

    [Fact]
    public void Editing_tracks_dirty_segments_and_ignores_surrounding_spaces()
    {
        var editor = Create();
        editor.EditCommand.Execute(null);

        editor.Segments[1].Text = "  Hi. ";
        Assert.False(editor.IsDirty);
        Assert.False(editor.SaveCommand.CanExecute(null));

        editor.Segments[0].Text = "We ship on Thursday.";
        Assert.True(editor.IsDirty);
        Assert.True(editor.SaveCommand.CanExecute(null));

        editor.Segments[0].Text = "We ship on Friday.";
        Assert.False(editor.IsDirty);
    }

    [Fact]
    public void Edit_mode_needs_a_finished_session_with_segments()
    {
        var editor = Create();
        Assert.True(editor.EditCommand.CanExecute(null));

        editor.IsLive = true;
        Assert.False(editor.EditCommand.CanExecute(null));

        editor.IsLive = false;
        editor.Load(new Transcript("raw", []));
        Assert.False(editor.EditCommand.CanExecute(null));
    }

    [Fact]
    public void Segments_show_time_label_and_speaker_colour()
    {
        var segment = Create().Segments[1];

        Assert.Equal("[00:01:05] Others", segment.Header);
        Assert.True(segment.IsSystem);
        Assert.False(segment.IsMic);
        Assert.Equal("[00:01:05] Others", segment.ToString());
    }

    // Save

    [Fact]
    public async Task Save_sends_only_real_changes_trimmed_then_reloads_and_suggests_minutes()
    {
        var editor = Create();
        editor.EditCommand.Execute(null);
        editor.Segments[0].Text = "  We ship on Thursday. ";
        editor.Segments[1].Text = "Hi. ";

        await editor.SaveCommand.ExecuteAsync(null);

        var (id, segments) = Assert.Single(_client.TranscriptUpdates);
        Assert.Equal(Id, id);
        Assert.Equal([new SegmentTextEdit("mic-000001", "We ship on Thursday.")], segments);
        Assert.False(editor.IsEditing);
        Assert.False(editor.IsDirty);
        Assert.True(editor.HasEdits);
        Assert.True(editor.SuggestRegenerate);
        Assert.Equal(1, _reloads);
        Assert.Equal("We ship on Thursday.", editor.Segments[0].OriginalText);
    }

    [Fact]
    public async Task An_empty_segment_is_not_sent()
    {
        var editor = Create();
        editor.EditCommand.Execute(null);
        editor.Segments[1].Text = "   ";

        await editor.SaveCommand.ExecuteAsync(null);

        Assert.Empty(_client.TranscriptUpdates);
        Assert.Equal(_localization["TranscriptEmptySegment"], editor.Error);
        Assert.True(editor.IsEditing);
    }

    [Fact]
    public async Task A_failed_save_keeps_the_changes_and_shows_the_error()
    {
        _client.TranscriptUpdateError = new EngineApiException(HttpStatusCode.UnprocessableEntity, "unknown_segment", "Reload the transcript.");
        var editor = Create();
        editor.EditCommand.Execute(null);
        editor.Segments[0].Text = "Changed.";

        await editor.SaveCommand.ExecuteAsync(null);

        Assert.Equal("Reload the transcript.", editor.Error);
        Assert.True(editor.IsEditing);
        Assert.True(editor.IsDirty);
        Assert.False(editor.IsSaving);
        Assert.False(editor.SuggestRegenerate);
    }

    [Fact]
    public async Task An_unreachable_engine_shows_the_localized_message()
    {
        _client.TranscriptUpdateError = new EngineUnavailableException("refused", new HttpRequestException());
        var editor = Create();
        editor.EditCommand.Execute(null);
        editor.Segments[0].Text = "Changed.";

        await editor.SaveCommand.ExecuteAsync(null);

        Assert.Equal(_localization["EngineUnavailable"], editor.Error);
    }

    [Fact]
    public void Cancel_discards_the_changes_and_leaves_edit_mode()
    {
        var editor = Create();
        editor.EditCommand.Execute(null);
        editor.Segments[0].Text = "Changed.";

        editor.CancelEditCommand.Execute(null);

        Assert.False(editor.IsEditing);
        Assert.False(editor.IsDirty);
        Assert.Equal("We ship on Friday.", editor.Segments[0].Text);
    }

    // Revert

    [Fact]
    public async Task Revert_asks_then_restores_the_original_transcript()
    {
        var editor = Create();
        editor.EditCommand.Execute(null);
        editor.Segments[0].Text = "Changed.";
        await editor.SaveCommand.ExecuteAsync(null);
        Assert.True(editor.RevertCommand.CanExecute(null));

        await editor.RevertCommand.ExecuteAsync(null);

        Assert.Equal([Id], _client.TranscriptReverts);
        Assert.Single(_dialogs.Asked);
        Assert.False(editor.HasEdits);
        Assert.Equal("We ship on Friday.", editor.Segments[0].Text);
        Assert.True(editor.SuggestRegenerate);
        Assert.False(editor.RevertCommand.CanExecute(null));
    }

    [Fact]
    public async Task Declining_the_revert_keeps_the_edits()
    {
        _client.Transcripts[Id] = Original with { Source = "edited" };
        _dialogs.Answer = false;
        var editor = Create();

        await editor.RevertCommand.ExecuteAsync(null);

        Assert.Empty(_client.TranscriptReverts);
        Assert.True(editor.HasEdits);
    }

    [Fact]
    public async Task A_failed_revert_shows_the_error()
    {
        _client.Transcripts[Id] = Original with { Source = "edited" };
        _client.TranscriptRevertError = new EngineApiException(HttpStatusCode.Conflict, "transcript_still_recording", "Still recording.");
        var editor = Create();

        await editor.RevertCommand.ExecuteAsync(null);

        Assert.Equal("Still recording.", editor.Error);
        Assert.True(editor.HasEdits);
    }

    [Fact]
    public void Revert_is_not_offered_while_editing_or_without_edits()
    {
        _client.Transcripts[Id] = Original with { Source = "edited" };
        var editor = Create();
        Assert.True(editor.RevertCommand.CanExecute(null));

        editor.EditCommand.Execute(null);
        Assert.False(editor.RevertCommand.CanExecute(null));

        editor.Load(Original);
        Assert.False(editor.RevertCommand.CanExecute(null));
    }

    // Navigation guard

    [Fact]
    public async Task Leaving_without_changes_does_not_ask()
    {
        var editor = Create();
        editor.EditCommand.Execute(null);

        Assert.True(await editor.ConfirmLeaveAsync());
        Assert.Empty(_dialogs.Asked);
    }

    [Fact]
    public async Task Leaving_with_changes_asks_and_discards_on_yes()
    {
        var editor = Create();
        editor.EditCommand.Execute(null);
        editor.Segments[0].Text = "Changed.";

        Assert.True(await editor.ConfirmLeaveAsync());

        Assert.Single(_dialogs.Asked);
        Assert.False(editor.IsDirty);
        Assert.False(editor.IsEditing);
    }

    [Fact]
    public async Task Leaving_with_changes_is_cancelled_on_no()
    {
        _dialogs.Answer = false;
        var editor = Create();
        editor.EditCommand.Execute(null);
        editor.Segments[0].Text = "Changed.";

        Assert.False(await editor.ConfirmLeaveAsync());

        Assert.True(editor.IsDirty);
        Assert.True(editor.IsEditing);
    }
}
