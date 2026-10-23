using System.Net;
using VozAta.Client;
using VozAta.Desktop.Services;
using VozAta.Desktop.Tests.Fakes;
using VozAta.Desktop.ViewModels;

namespace VozAta.Desktop.Tests;

/// <summary>Minutes of a part of a recorded meeting (phase 49).</summary>
public sealed class RangeMinutesViewModelTests
{
    private const string SessionId = "20261016_090000";
    private const double Length = 1800.4; // 00:30:00.4

    private readonly FakeEngineClient _client = new();
    private readonly LocalizationService _localization = new();
    private double? _player;
    private readonly string? _template = "daily";

    private RangeMinutesViewModel Create() =>
        new(_client, _localization, SessionId, Length, () => _player, () => _template);

    [Theory]
    [InlineData("00:02:32", 152)]
    [InlineData("2:32", 152)]
    [InlineData("1:02:03", 3723)]
    [InlineData(" 90 ", 90)]
    [InlineData("00:00:00", 0)]
    public void Times_are_read_as_hours_minutes_and_seconds(string text, double seconds)
    {
        Assert.True(TimeText.TryParse(text, out var parsed));
        Assert.Equal(seconds, parsed);
    }

    [Theory]
    [InlineData("")]
    [InlineData(null)]
    [InlineData("00:61:00")]
    [InlineData("1:2:60")]
    [InlineData("a:00")]
    [InlineData("-1:00")]
    [InlineData("1:2:3:4")]
    [InlineData("1.5")]
    public void Other_text_is_not_a_time(string? text) => Assert.False(TimeText.TryParse(text, out _));

    [Fact]
    public void The_whole_meeting_is_the_default_part()
    {
        var range = Create();

        Assert.Equal(("00:00:00", "00:30:01"), (range.From, range.To));
        Assert.Null(range.ValidationError);
        Assert.True(range.GenerateCommand.CanExecute(null));
    }

    [Theory]
    [InlineData("00:12:54", "00:02:32", "RangeEndBeforeStart")]
    [InlineData("00:02:32", "00:02:32", "RangeEndBeforeStart")]
    [InlineData("2:7x", "00:12:54", "RangeInvalidTime")]
    [InlineData("00:02:32", "00:31:00", "RangeBeyondEnd")]
    public void Invalid_parts_say_why_and_cannot_be_written(string from, string to, string key)
    {
        var range = Create();

        range.From = from;
        range.To = to;

        var expected = key == "RangeBeyondEnd" ? _localization.Format(key, "00:30:01") : _localization[key];
        Assert.Equal(expected, range.ValidationError);
        Assert.False(range.GenerateCommand.CanExecute(null));
    }

    [Fact]
    public async Task Writing_sends_the_part_and_the_template_then_waits_for_the_engine()
    {
        var range = Create();
        range.From = "2:32";
        range.To = "00:12:54";

        await range.GenerateCommand.ExecuteAsync(null);

        Assert.Equal([(SessionId, (double?)152, (double?)774, (string?)"daily")], _client.PartialRequests);
        Assert.True(range.IsWriting);
        Assert.False(range.GenerateCommand.CanExecute(null));
        Assert.False(range.OnReady(new PartialMinutesReadyEvent("other", "p", 0, 1, "range")));
        Assert.True(range.OnReady(new PartialMinutesReadyEvent(SessionId, "p1", 152, 774, "range")));
        Assert.False(range.IsWriting);
        Assert.False(range.OnReady(new PartialMinutesReadyEvent(SessionId, "p2", 0, 1, "button"))); // not asked here
    }

    [Fact]
    public async Task A_failure_ends_with_the_engine_message()
    {
        var range = Create();
        await range.GenerateCommand.ExecuteAsync(null);

        range.OnError(SessionId, "translation_failed", "other");
        Assert.True(range.IsWriting);
        range.OnError(SessionId, "empty_range", "Nothing was said in that part.");

        Assert.False(range.IsWriting);
        Assert.Equal("Nothing was said in that part.", range.Error);
    }

    [Fact]
    public async Task A_refused_request_is_shown()
    {
        _client.PartialMinutesError = new EngineApiException(HttpStatusCode.UnprocessableEntity, "invalid_range", "Bad range.");
        var range = Create();

        await range.GenerateCommand.ExecuteAsync(null);

        Assert.False(range.IsWriting);
        Assert.Equal("Bad range.", range.Error);
    }

    [Fact]
    public void The_player_and_transcript_lines_set_the_times()
    {
        var range = Create();
        Assert.False(range.FromPlayerCommand.CanExecute(null));

        _player = 152.7;
        range.PlayerChanged();
        range.FromPlayerCommand.Execute(null);
        _player = 773.2;
        range.ToPlayerCommand.Execute(null);
        Assert.Equal(("00:02:32", "00:12:54"), (range.From, range.To));

        range.StartAt(new TranscriptLine("00:01:00", "Ana", "Hi.", "mic") { Start = 60.4, End = 62 });
        range.EndAt(new TranscriptLine("00:05:00", "Ana", "Bye.", "mic") { Start = 300, End = 303.2 });
        Assert.Equal(("00:01:00", "00:05:04"), (range.From, range.To));
    }

    [Fact]
    public async Task The_meeting_page_opens_the_partial_minutes_tab_for_its_part()
    {
        var summary = new SessionSummary(SessionId, "done", DateTimeOffset.Now, null, Length, "pt", true);
        var page = new SessionPageViewModel(_client, new FakeShell(), _localization, new FakeFileSaver(), summary);
        page.RangeEndHereCommand.Execute(new TranscriptLine("00:00:10", "Ana", "Hi.", "mic") { Start = 10, End = 12 });
        Assert.Equal(SessionPageViewModel.PartialMinutesTab, page.SelectedTab);
        page.SelectedTab = SessionPageViewModel.TranscriptTab;
        await page.Range.GenerateCommand.ExecuteAsync(null);
        _client.PartialMinutes[SessionId] = [new PartialMinutesDetail("p1", "t", 0, 12, "range", null, "# A\n")];

        await page.OnPartialMinutesReadyAsync(new PartialMinutesReadyEvent(SessionId, "p1", 0, 12, "range"));

        Assert.Equal(SessionPageViewModel.PartialMinutesTab, page.SelectedTab);
        Assert.Equal("p1", page.Partials.Selected?.Summary.Id);
        page.OnError(SessionId, "empty_range", "x"); // nothing is being written any more
        Assert.Null(page.Range.Error);
    }
}
