using System.Globalization;
using System.Net;
using System.Text.Json;
using VozAta.Client;
using VozAta.Desktop.Services;
using VozAta.Desktop.Tests.Fakes;
using VozAta.Desktop.ViewModels;

namespace VozAta.Desktop.Tests;

/// <summary>A clock at noon local time on Friday 2026-10-16 (the same day in every time zone).</summary>
internal sealed class NoonClock : IClock
{
    public DateTimeOffset Now { get; set; } = Local(2026, 10, 16, 12);

    public static DateTimeOffset Local(int year, int month, int day, int hour, int minute = 0)
    {
        var time = new DateTime(year, month, day, hour, minute, 0, DateTimeKind.Unspecified);
        return new DateTimeOffset(time, TimeZoneInfo.Local.GetUtcOffset(time));
    }
}

public sealed class MeetingsPageViewModelTests
{
    private static readonly CultureInfo English = CultureInfo.GetCultureInfo("en");

    private readonly FakeEngineClient _client = new();
    private readonly FakeDialogs _dialogs = new();
    private readonly FakeShell _shell = new();
    private readonly FakeFileSaver _saver = new();
    private readonly NoonClock _clock = new();
    private readonly ManualDelay _undoDelay = new();
    private readonly ManualDelay _searchDelay = new();
    private readonly LocalizationService _localization = new();

    private MeetingsPageViewModel CreateWithAudioFolder(string folder)
    {
        var history = new HistoryViewModel(_client, _shell, _localization, _saver, searchDelay: _searchDelay.Wait, dialogs: _dialogs);
        return new MeetingsPageViewModel(_client, history, _localization, _clock, _dialogs, _shell, _saver, delay: _undoDelay.Wait)
        {
            AudioFolder = folder,
        };
    }

    private MeetingsPageViewModel Create()
    {
        var history = new HistoryViewModel(_client, _shell, _localization, _saver, searchDelay: _searchDelay.Wait, dialogs: _dialogs);
        return new MeetingsPageViewModel(_client, history, _localization, _clock, _dialogs, _shell, _saver, delay: _undoDelay.Wait);
    }

    private SessionSummary Add(
        DateTimeOffset start, double seconds, string? title = null, string status = "done",
        int speakers = 0, string? template = null, string? language = "en")
    {
        var id = start.ToString("yyyyMMdd_HHmmss", CultureInfo.InvariantCulture);
        var live = status is "recording" or "paused" or "finalizing";
        var summary = new SessionSummary(
            id, status, start, live ? null : start.AddSeconds(seconds), seconds, language, false, title, speakers, false, template);
        _client.Sessions.Add(summary);
        return summary;
    }

    private static IEnumerable<MeetingRow> Rows(MeetingsPageViewModel page) =>
        page.Weeks.SelectMany(week => week.Days).SelectMany(day => day.Rows);

    private static string Time(DateTimeOffset time) => time.ToLocalTime().ToString("t", English);

    // Grouping and totals

    [Fact]
    public async Task Meetings_are_grouped_by_day_with_day_and_week_totals()
    {
        var monday = Add(NoonClock.Local(2026, 10, 12, 9), 1800);
        var weekly = Add(NoonClock.Local(2026, 10, 14, 9), 3600, "Weekly sync", speakers: 3, template: "daily");
        var afternoon = Add(NoonClock.Local(2026, 10, 14, 15, 30), 600.5, language: "pt");
        var today = Add(NoonClock.Local(2026, 10, 16, 8), 59);
        var page = Create();

        await page.LoadAsync();

        Assert.Equal([(new DateOnly(2026, 10, 12), new DateOnly(2026, 10, 18))], _client.DayRequests);
        var week = Assert.Single(page.Weeks);
        Assert.Equal(("This week", "This week", "1:40:59"), (week.Label, page.WeekLabel, page.WeekTotal));
        Assert.Equal(["Today", "Wed, 14 Oct", "Mon, 12 Oct"], week.Days.Select(day => day.Label));
        Assert.Equal(["0:00:59", "1:10:00", "0:30:00"], week.Days.Select(day => day.Total));
        Assert.Equal("1:40:59", week.Total);
        Assert.Equal([today.Id, afternoon.Id, weekly.Id, monday.Id], Rows(page).Select(row => row.Id));

        var titled = Rows(page).Single(row => row.Id == weekly.Id);
        Assert.Equal(("Weekly sync", false, "1:00:00"), (titled.DisplayTitle, titled.IsUntitled, titled.Duration));
        Assert.Equal(["daily", "English"], titled.Tags);
        Assert.Equal((3, true, "3 speakers identified"), (titled.SpeakerCount, titled.HasSpeakers, titled.SpeakersText));
        Assert.Equal($"{Time(weekly.StartedAt!.Value)} – {Time(weekly.EndedAt!.Value)}", titled.TimeRange);
        Assert.Equal(["Markdown", "Word", "PDF", "ZIP"], titled.Exports.Select(export => export.Format switch
        {
            "md" => "Markdown",
            "docx" => "Word",
            "pdf" => "PDF",
            _ => "ZIP",
        }));

        var untitled = Rows(page).Single(row => row.Id == afternoon.Id);
        Assert.Equal(("Untitled meeting", true, false), (untitled.DisplayTitle, untitled.IsUntitled, untitled.HasSpeakers));
        Assert.Equal(["Portuguese"], untitled.Tags);
        Assert.Equal("0:10:00", untitled.Duration);
        Assert.Contains("Untitled meeting", untitled.ToString(), StringComparison.Ordinal);
        Assert.False(page.IsEmpty);
        Assert.True(page.IsThisWeek);
    }

    [Fact]
    public async Task Yesterday_is_named_and_template_names_come_from_the_engine()
    {
        Add(NoonClock.Local(2026, 10, 15, 10), 60, template: "daily");
        _client.Templates.Clear();
        _client.Templates.Add(new MinutesTemplate("daily", "Daily standup"));
        var templates = new MinutesTemplatesViewModel(_client);
        await templates.LoadAsync();
        var history = new HistoryViewModel(_client, _shell, _localization, _saver);
        var page = new MeetingsPageViewModel(_client, history, _localization, _clock, _dialogs, _shell, _saver, templates);

        await page.LoadAsync();

        Assert.Equal("Yesterday", page.Weeks[0].Days[0].Label);
        Assert.Equal(["Daily standup", "English"], Rows(page).Single().Tags);
    }

    [Fact]
    public async Task An_empty_week_is_empty_and_errors_are_shown()
    {
        var page = Create();

        await page.LoadAsync();
        Assert.True(page.IsEmpty);
        Assert.Equal("0:00:00", page.WeekTotal);

        _client.DaysError = new EngineUnavailableException("refused", new HttpRequestException("refused"));
        await page.RefreshCommand.ExecuteAsync(null);

        Assert.Equal(_localization["EngineUnavailable"], page.Error);
        Assert.False(page.IsEmpty);
    }

    [Fact]
    public async Task The_live_meeting_is_pinned_on_top_and_counts_in_the_week()
    {
        Add(NoonClock.Local(2026, 10, 16, 9), 600);
        var live = Add(NoonClock.Local(2026, 10, 16, 11, 30), 120, "Client call", status: "recording");
        var page = Create();

        await page.LoadAsync();

        Assert.NotNull(page.Live);
        Assert.Equal(live.Id, page.Live.Id);
        Assert.True(page.Live.IsLive);
        Assert.False(page.Live.CanDelete);
        Assert.Equal($"{Time(live.StartedAt!.Value)} –", page.Live.TimeRange);
        Assert.DoesNotContain(Rows(page), row => row.Id == live.Id);
        Assert.Equal("0:12:00", page.WeekTotal);
    }

    // Week navigation and infinite scroll

    [Fact]
    public async Task Week_navigation_moves_a_week_at_a_time_and_back_to_this_week()
    {
        Add(NoonClock.Local(2026, 10, 7, 10), 60);
        var page = Create();
        await page.LoadAsync();
        Assert.False(page.NextWeekCommand.CanExecute(null));
        Assert.False(page.ThisWeekCommand.CanExecute(null));

        await page.PreviousWeekCommand.ExecuteAsync(null);

        Assert.Equal(new DateOnly(2026, 10, 5), page.WeekStart);
        Assert.Equal(("Last week", "0:01:00"), (page.WeekLabel, page.WeekTotal));
        Assert.True(page.NextWeekCommand.CanExecute(null));
        Assert.Equal((new DateOnly(2026, 10, 5), new DateOnly(2026, 10, 11)), _client.DayRequests[^1]);

        await page.PreviousWeekCommand.ExecuteAsync(null);
        Assert.Equal("28 Sept – 4 Oct", page.WeekLabel.Replace("Sep ", "Sept ", StringComparison.Ordinal));
        Assert.True(page.IsEmpty);

        await page.NextWeekCommand.ExecuteAsync(null);
        Assert.Equal(new DateOnly(2026, 10, 5), page.WeekStart);
        await page.ThisWeekCommand.ExecuteAsync(null);
        Assert.Equal(new DateOnly(2026, 10, 12), page.WeekStart);
        Assert.True(page.IsThisWeek);
        Assert.Equal((new DateOnly(2026, 10, 12), new DateOnly(2026, 10, 18)), _client.DayRequests[^1]);
    }

    [Fact]
    public async Task Scrolling_down_loads_older_weeks_skipping_empty_ones()
    {
        Add(NoonClock.Local(2026, 10, 13, 10), 60);
        var old = Add(NoonClock.Local(2026, 9, 23, 10), 120, "Planning");
        var page = Create();
        await page.LoadAsync();
        Assert.True(page.HasEarlier);
        Assert.True(page.LoadOlderCommand.CanExecute(null));

        await page.LoadOlderCommand.ExecuteAsync(null);

        Assert.Equal(
            [
                (new DateOnly(2026, 10, 12), new DateOnly(2026, 10, 18)),
                (new DateOnly(2026, 10, 5), new DateOnly(2026, 10, 11)),
                (new DateOnly(2026, 9, 28), new DateOnly(2026, 10, 4)),
                (new DateOnly(2026, 9, 21), new DateOnly(2026, 9, 27)),
            ],
            _client.DayRequests);
        Assert.Equal(2, page.Weeks.Count);
        Assert.Equal(new DateOnly(2026, 9, 21), page.Weeks[1].Start);
        Assert.Equal(old.Id, page.Weeks[1].Days.Single().Rows.Single().Id);
        Assert.Equal("0:01:00", page.WeekTotal); // the header keeps the week on top
        Assert.False(page.HasEarlier);
        Assert.False(page.LoadOlderCommand.CanExecute(null));

        await page.LoadAsync(); // a refresh reloads every loaded week at once
        Assert.Equal((new DateOnly(2026, 9, 21), new DateOnly(2026, 10, 18)), _client.DayRequests[^1]);
        Assert.Equal(2, page.Weeks.Count);
    }

    [Fact]
    public async Task Loading_older_weeks_stops_after_the_empty_week_limit_and_reports_errors()
    {
        Add(NoonClock.Local(2025, 1, 6, 10), 60); // far back
        var page = Create();
        await page.LoadAsync();

        await page.LoadOlderCommand.ExecuteAsync(null);

        Assert.Equal(1 + MeetingsPageViewModel.MaxEmptyWeeks, _client.DayRequests.Count);
        Assert.Empty(page.Weeks);
        Assert.True(page.HasEarlier); // the next scroll goes on

        _client.DaysError = new EngineApiException(HttpStatusCode.InternalServerError, "internal_error", "Boom");
        await page.LoadOlderCommand.ExecuteAsync(null);
        Assert.Equal("Boom", page.Error);
        Assert.False(page.IsLoadingOlder);
    }

    // Open and select

    [Fact]
    public async Task Clicking_a_row_opens_its_detail_and_marks_it_selected()
    {
        var meeting = Add(NoonClock.Local(2026, 10, 14, 9), 60, "Retro");
        _client.Details[meeting.Id] = new SessionDetail(meeting.Id, "done", null, null, 60, "en", false, [], @"C:\rec");
        var page = Create();
        await page.LoadAsync();
        var row = Rows(page).Single();

        page.OpenCommand.Execute(row);
        await page.History.DetailLoading;

        Assert.Equal(meeting.Id, page.History.Detail?.Id);
        Assert.Equal("Retro", page.History.Detail?.Title);
        Assert.True(row.IsSelected);

        row.IsEditing = true;
        page.OpenCommand.Execute(null); // nothing to open
        Assert.True(row.IsSelected);
    }

    // Rename

    [Fact]
    public async Task Rename_saves_on_enter_and_shows_the_new_title()
    {
        var meeting = Add(NoonClock.Local(2026, 10, 14, 9), 60);
        var page = Create();
        await page.LoadAsync();
        var row = Rows(page).Single();

        page.BeginRenameCommand.Execute(row);
        Assert.True(row.IsEditing);
        Assert.Equal("", row.EditTitle);
        row.EditTitle = "  Kick-off  ";
        await page.SaveRenameCommand.ExecuteAsync(row);

        Assert.Equal([(meeting.Id, (string?)"Kick-off")], _client.TitleUpdates);
        var renamed = Rows(page).Single();
        Assert.Equal(("Kick-off", false, false), (renamed.DisplayTitle, renamed.IsUntitled, renamed.IsEditing));
    }

    [Fact]
    public async Task Rename_cancels_on_escape_skips_unchanged_titles_and_clears_blank_ones()
    {
        var meeting = Add(NoonClock.Local(2026, 10, 14, 9), 60, "Draft");
        var other = Add(NoonClock.Local(2026, 10, 13, 9), 60, "Other");
        var page = Create();
        await page.LoadAsync();
        var row = Rows(page).Single(item => item.Id == meeting.Id);
        var second = Rows(page).Single(item => item.Id == other.Id);

        page.BeginRenameCommand.Execute(second);
        page.BeginRenameCommand.Execute(row); // one title box at a time
        Assert.False(second.IsEditing);
        Assert.Equal("Draft", row.EditTitle);
        row.EditTitle = "Something else";
        page.CancelRenameCommand.Execute(row);
        Assert.False(row.IsEditing);
        await page.SaveRenameCommand.ExecuteAsync(row); // not editing: nothing to save

        page.BeginRenameCommand.Execute(row);
        await page.SaveRenameCommand.ExecuteAsync(row); // unchanged
        Assert.Empty(_client.TitleUpdates);
        Assert.False(row.IsEditing);

        page.BeginRenameCommand.Execute(row);
        row.EditTitle = "   ";
        await page.SaveRenameCommand.ExecuteAsync(row);
        Assert.Equal([(meeting.Id, (string?)null)], _client.TitleUpdates);
        Assert.Equal("Untitled meeting", Rows(page).Single(item => item.Id == meeting.Id).DisplayTitle);
        page.BeginRenameCommand.Execute(null);
        page.CancelRenameCommand.Execute(null);
    }

    [Fact]
    public async Task A_failed_rename_keeps_the_title_box_open_with_the_error()
    {
        Add(NoonClock.Local(2026, 10, 14, 9), 60, "Draft");
        _client.TitleError = new EngineApiException(HttpStatusCode.UnprocessableEntity, "title_too_long", "Too long.");
        var page = Create();
        await page.LoadAsync();
        var row = Rows(page).Single();

        page.BeginRenameCommand.Execute(row);
        row.EditTitle = new string('x', 300);
        await page.SaveRenameCommand.ExecuteAsync(row);

        Assert.True(row.IsEditing);
        Assert.Equal("Too long.", page.Error);
    }

    // Delete

    [Fact]
    public async Task A_file_backend_delete_waits_for_the_undo_window_then_goes_to_the_recycle_bin()
    {
        var meeting = Add(NoonClock.Local(2026, 10, 14, 9), 60, "Retro");
        var page = Create();
        await page.LoadAsync();

        await page.DeleteCommand.ExecuteAsync(Rows(page).Single());

        Assert.Equal(["Delete meeting?"], _dialogs.Asked);
        Assert.Contains("Recycle Bin", _dialogs.Messages.Single(), StringComparison.Ordinal);
        Assert.Contains("“Retro”", _dialogs.Messages.Single(), StringComparison.Ordinal);
        Assert.Empty(Rows(page));
        Assert.Equal("0:00:00", page.WeekTotal);
        Assert.Equal("“Retro” moved to the Recycle Bin.", page.Toast);
        Assert.True(page.CanUndo);
        Assert.Empty(_client.Deleted);
        Assert.Equal([MeetingsPageViewModel.UndoWindow], _undoDelay.Requested);

        _undoDelay.Elapse();
        await page.PendingDelete;

        Assert.Equal([meeting.Id], _client.Deleted);
        Assert.Null(page.Toast);
        Assert.False(page.CanUndo);
        Assert.True(page.IsEmpty);
    }

    [Fact]
    public async Task Undo_brings_the_meeting_back_without_deleting_it()
    {
        Add(NoonClock.Local(2026, 10, 14, 9), 60, "Retro");
        var page = Create();
        await page.LoadAsync();

        await page.DeleteCommand.ExecuteAsync(Rows(page).Single());
        page.UndoCommand.Execute(null);
        await page.PendingDelete;

        Assert.Equal("Retro", Rows(page).Single().DisplayTitle);
        Assert.Empty(_client.Deleted);
        Assert.Null(page.Toast);
        Assert.False(page.UndoCommand.CanExecute(null));
        page.UndoCommand.Execute(null); // nothing pending: no-op
    }

    [Fact]
    public async Task A_database_delete_is_permanent_and_immediate()
    {
        var meeting = Add(NoonClock.Local(2026, 10, 14, 9), 60);
        _client.Storage = "sqlite";
        var page = Create();
        await page.LoadAsync();

        await page.DeleteCommand.ExecuteAsync(Rows(page).Single());

        Assert.Contains("permanently", _dialogs.Messages.Single(), StringComparison.Ordinal);
        Assert.Contains("“Untitled meeting”", _dialogs.Messages.Single(), StringComparison.Ordinal);
        Assert.Equal([meeting.Id], _client.Deleted);
        Assert.Empty(_undoDelay.Requested);
        Assert.Equal("“Untitled meeting” was deleted.", page.Toast);
        Assert.False(page.CanUndo);
        Assert.Empty(Rows(page));

        await page.DismissToastCommand.ExecuteAsync(null);
        Assert.Null(page.Toast);
    }

    [Fact]
    public async Task A_cancelled_delete_and_the_live_meeting_keep_their_rows()
    {
        Add(NoonClock.Local(2026, 10, 14, 9), 60);
        Add(NoonClock.Local(2026, 10, 16, 11), 60, status: "paused");
        _dialogs.Answer = false;
        var page = Create();
        await page.LoadAsync();

        await page.DeleteCommand.ExecuteAsync(Rows(page).Single());
        await page.DeleteCommand.ExecuteAsync(page.Live);
        await page.DeleteCommand.ExecuteAsync(null);

        Assert.Single(_dialogs.Asked); // the live meeting is not even asked about
        Assert.Single(Rows(page));
        Assert.NotNull(page.Live);
        Assert.Empty(_client.Deleted);
    }

    [Fact]
    public async Task A_failed_delete_brings_the_meeting_back_with_the_error()
    {
        Add(NoonClock.Local(2026, 10, 14, 9), 60, "Retro");
        _client.Storage = "sqlite";
        _client.DeleteError = new EngineApiException(HttpStatusCode.Conflict, "session_still_active", "Still finalizing.");
        var page = Create();
        await page.LoadAsync();

        await page.DeleteCommand.ExecuteAsync(Rows(page).Single());

        Assert.Equal("Still finalizing.", page.Error);
        Assert.Equal("Retro", Rows(page).Single().DisplayTitle);
        Assert.Null(page.Toast);
    }

    [Fact]
    public async Task A_second_delete_or_closing_the_toast_deletes_the_pending_one_at_once()
    {
        var first = Add(NoonClock.Local(2026, 10, 14, 9), 60, "First");
        var second = Add(NoonClock.Local(2026, 10, 13, 9), 60, "Second");
        var page = Create();
        await page.LoadAsync();

        await page.DeleteCommand.ExecuteAsync(Rows(page).Single(row => row.Id == first.Id));
        await page.DeleteCommand.ExecuteAsync(Rows(page).Single(row => row.Id == second.Id));

        Assert.Equal([first.Id], _client.Deleted);
        Assert.Equal("“Second” moved to the Recycle Bin.", page.Toast);

        await page.DismissToastCommand.ExecuteAsync(null);
        await page.PendingDelete;
        Assert.Equal([first.Id, second.Id], _client.Deleted);
        Assert.True(page.IsEmpty);

        await page.CommitPendingAsync(); // nothing left
        Assert.Equal(2, _client.Deleted.Count);
    }

    [Fact]
    public async Task Deleting_the_open_meeting_closes_its_detail()
    {
        var meeting = Add(NoonClock.Local(2026, 10, 14, 9), 60, "Retro");
        _client.Details[meeting.Id] = new SessionDetail(meeting.Id, "done", null, null, 60, "en", false, [], @"C:\rec");
        var page = Create();
        await page.LoadAsync();
        await page.History.LoadAsync();
        page.OpenCommand.Execute(Rows(page).Single());
        await page.History.DetailLoading;

        await page.DeleteCommand.ExecuteAsync(Rows(page).Single());

        Assert.Null(page.History.Detail);
        Assert.Null(page.History.Selected);
        Assert.Empty(page.History.Rows);
    }

    // Play and export

    [Fact]
    public async Task Play_downloads_the_mixed_recording_or_says_there_is_none()
    {
        var withAudio = Add(NoonClock.Local(2026, 10, 14, 9), 60);
        var without = Add(NoonClock.Local(2026, 10, 13, 9), 60);
        // a sqlite session: no folder or files, the audio comes from the engine (phase 32)
        _client.Details[withAudio.Id] = new SessionDetail(withAudio.Id, "done", null, null, 60, "en", false, null, null, new Dictionary<string, double> { ["mic"] = 60, ["mixed"] = 60 });
        _client.Details[without.Id] = new SessionDetail(without.Id, "done", null, null, 60, "en", false, ["mic.wav"], @"C:\rec\b", new Dictionary<string, double> { ["mic"] = 60 });
        var folder = Path.Combine(Path.GetTempPath(), "VozAta.Tests", Guid.NewGuid().ToString("N"));
        var page = CreateWithAudioFolder(folder);
        await page.LoadAsync();

        try
        {
            await page.PlayCommand.ExecuteAsync(Rows(page).Single(row => row.Id == without.Id));
            Assert.Equal(_localization["MeetingNoAudio"], page.Error);

            await page.PlayCommand.ExecuteAsync(Rows(page).Single(row => row.Id == withAudio.Id));
            var path = Path.Combine(folder, $"{withAudio.Id}-mixed.wav");
            Assert.Equal([path], _shell.Opened);
            Assert.Equal([(withAudio.Id, "mixed")], _client.AudioDownloads);
            Assert.True(File.Exists(path));
            Assert.Null(page.Error);

            _client.AudioError = new IOException("disk full");
            await page.PlayCommand.ExecuteAsync(Rows(page).Single(row => row.Id == withAudio.Id));
            Assert.Equal("disk full", page.Error);
            _client.AudioError = null;
        }
        finally
        {
            if (Directory.Exists(folder))
            {
                Directory.Delete(folder, recursive: true);
            }
        }

        _client.DetailError = new EngineUnavailableException("refused", new HttpRequestException("refused"));
        await page.PlayCommand.ExecuteAsync(Rows(page).First());
        await page.PlayCommand.ExecuteAsync(null);
        Assert.Equal(_localization["EngineUnavailable"], page.Error);
    }

    [Fact]
    public async Task Export_offers_the_formats_and_saves_the_chosen_one()
    {
        var meeting = Add(NoonClock.Local(2026, 10, 14, 9), 60);
        var other = Add(NoonClock.Local(2026, 10, 13, 9), 60);
        var page = Create();
        await page.LoadAsync();
        var row = Rows(page).Single(item => item.Id == meeting.Id);
        var second = Rows(page).Single(item => item.Id == other.Id);

        page.ToggleExportCommand.Execute(second);
        page.ToggleExportCommand.Execute(row);
        Assert.True(row.IsExportOpen);
        Assert.False(second.IsExportOpen); // one menu at a time
        await page.ExportCommand.ExecuteAsync(row.Exports.Single(export => export.Format == "docx"));

        Assert.False(row.IsExportOpen);
        var save = Assert.Single(_saver.Saves);
        Assert.Equal(($"{meeting.Id}-minutes.docx", "docx"), (save.Name, save.Extension));
        Assert.Equal(_localization.Format("ExportSaved", _saver.Path), page.Message);

        _client.ExportError = new EngineApiException(HttpStatusCode.NotFound, "session_not_found", "Gone.");
        await page.ExportCommand.ExecuteAsync(row.Exports[0]);
        await page.ExportCommand.ExecuteAsync(null);
        page.ToggleExportCommand.Execute(null);
        Assert.Equal("Gone.", page.Error);
        Assert.Equal("Export Markdown", row.Exports[0].ToString());
    }

    // Search

    [Fact]
    public async Task Search_lists_the_matching_meetings_with_their_snippets()
    {
        var loaded = Add(NoonClock.Local(2026, 10, 14, 9), 60, "Weekly sync");
        const string Older = "20260901_100000";
        _client.Details[Older] = new SessionDetail(Older, "done", NoonClock.Local(2026, 9, 1, 10), null, 1800, "pt", true, [], @"C:\rec")
        {
            Metadata = new Dictionary<string, JsonElement>
            {
                ["title"] = JsonSerializer.SerializeToElement("Budget review"),
                ["speaker_count"] = JsonSerializer.SerializeToElement(2),
                ["has_action_items"] = JsonSerializer.SerializeToElement(true),
                ["template"] = JsonSerializer.SerializeToElement("client"),
            },
        };
        _client.SearchHits.Add(new SearchHit(loaded.Id, "mic-000001", 5, "mic", "Me", "the \u0002deck\u0003 is ready"));
        _client.SearchHits.Add(new SearchHit(Older, "system-000004", 65, "system", "Others", "send the \u0002deck\u0003"));
        _client.SearchHits.Add(new SearchHit("20260101_090000", "mic-000002", 1, "mic", "Me", "\u0002deck\u0003"));
        var page = Create();
        await page.LoadAsync();

        page.Search.Query = "deck";
        _searchDelay.Elapse();
        await page.Search.Pending;
        await page.MatchesLoading;

        Assert.Equal([loaded.Id, Older, "20260101_090000"], page.Matches.Select(match => match.SessionId));
        Assert.Equal(("Weekly sync", false), (page.Matches[0].Title, page.Matches[0].IsUntitled));
        Assert.Contains("0:01:00", page.Matches[0].Details, StringComparison.Ordinal);
        Assert.Equal("Budget review", page.Matches[1].Title);
        Assert.Equal((2, true), (page.Matches[1].Row!.SpeakerCount, page.Matches[1].Row!.Summary.HasActionItems));
        Assert.Equal("client", page.Matches[1].Row!.Summary.Template);
        Assert.Equal("2026-01-01 09:00", page.Matches[2].Title); // unknown: the date stands in
        Assert.Equal("", page.Matches[2].Details);
        Assert.Single(page.Matches[1].Snippets);
        Assert.Equal("Budget review", page.Matches[1].ToString());

        page.OpenMatchCommand.Execute(page.Matches[1]);
        Assert.Equal(Older, page.History.Selected?.Id);
        Assert.True(page.Matches[1].Row!.IsSelected);

        page.Search.Query = "";
        Assert.Empty(page.Matches);
    }

    [Fact]
    public async Task A_renamed_meeting_is_renamed_in_the_search_matches_too()
    {
        var meeting = Add(NoonClock.Local(2026, 10, 14, 9), 60, "Draft");
        _client.SearchHits.Add(new SearchHit(meeting.Id, "mic-000001", 5, "mic", "Me", "\u0002deck\u0003"));
        var page = Create();
        await page.LoadAsync();
        page.Search.Query = "deck";
        _searchDelay.Elapse();
        await page.Search.Pending;

        var row = Rows(page).Single();
        page.BeginRenameCommand.Execute(row);
        row.EditTitle = "Final";
        await page.SaveRenameCommand.ExecuteAsync(row);

        Assert.Equal("Final", page.Matches.Single().Title);
    }

    // Language and formats

    [Fact]
    public async Task Texts_follow_the_interface_language()
    {
        Add(NoonClock.Local(2026, 10, 16, 9), 60);
        Add(NoonClock.Local(2026, 10, 14, 9), 60);
        var page = Create();
        await page.LoadAsync();

        _localization.SetLanguage("pt-BR");
        page.RefreshTexts();

        Assert.Equal(("Esta semana", "Hoje"), (page.WeekLabel, page.Weeks[0].Days[0].Label));
        Assert.Equal("Reunião sem título", Rows(page).First().DisplayTitle);
        Assert.StartsWith("qua", page.Weeks[0].Days[1].Label, StringComparison.Ordinal);
    }

    [Theory]
    [InlineData(0, "0:00:00")]
    [InlineData(-5, "0:00:00")]
    [InlineData(59.9, "0:00:59")]
    [InlineData(3725.6, "1:02:05")]
    [InlineData(36000, "10:00:00")]
    public void Durations_use_toggl_format(double seconds, string expected) =>
        Assert.Equal(expected, MeetingsPageViewModel.FormatDuration(seconds));

    [Theory]
    [InlineData(2026, 10, 12, 2026, 10, 12)]
    [InlineData(2026, 10, 18, 2026, 10, 12)]
    [InlineData(2026, 10, 16, 2026, 10, 12)]
    [InlineData(2026, 10, 19, 2026, 10, 19)]
    public void Weeks_start_on_monday(int year, int month, int day, int startYear, int startMonth, int startDay) =>
        Assert.Equal(
            new DateOnly(startYear, startMonth, startDay),
            MeetingsPageViewModel.StartOfWeek(new DateOnly(year, month, day)));

    [Fact]
    public async Task A_meeting_without_a_start_has_no_time_and_one_without_an_end_uses_its_duration()
    {
        var noEnd = new SessionSummary("20261014_090000", "done", NoonClock.Local(2026, 10, 14, 9), null, 600, null, false);
        _client.Sessions.Add(noEnd);
        var page = Create();
        await page.LoadAsync();

        var row = Rows(page).Single();
        Assert.Equal($"{Time(noEnd.StartedAt!.Value)} – {Time(noEnd.StartedAt!.Value.AddMinutes(10))}", row.TimeRange);
        Assert.Empty(row.Tags);
        Assert.Equal("Wed, 14 Oct, 0:10:00", page.Weeks[0].Days[0].ToString());
        Assert.Equal("This week, 0:10:00", page.Weeks[0].ToString());
    }

    // Meeting ZIPs (phase 39)

    [Fact]
    public async Task A_row_exports_the_recording_as_a_zip()
    {
        var meeting = Add(NoonClock.Local(2026, 10, 14, 9), 60);
        _saver.Path = @"C:\Users\me\meeting.zip";
        var page = Create();
        await page.LoadAsync();
        var row = Rows(page).Single();
        var zip = row.Exports.Single(export => export.Format == "zip");

        await page.ExportCommand.ExecuteAsync(zip);

        Assert.Equal("Export recording (.zip)", zip.Label);
        Assert.Equal([meeting.Id], _client.BundleDownloads);
        var save = Assert.Single(_saver.StreamSaves);
        Assert.Equal(($"{meeting.Id}.zip", "ZIP archive", "zip"), (save.Name, save.TypeName, save.Extension));
        Assert.Empty(_saver.Saves);
        Assert.Equal(_localization.Format("ExportSaved", _saver.Path), page.Message);
    }

    [Fact]
    public async Task Importing_a_zip_refreshes_the_list_and_opens_the_meeting()
    {
        var meeting = Add(NoonClock.Local(2026, 10, 14, 9), 60, "Retro");
        _client.Details[meeting.Id] = Detail(meeting.Id, "Retro");
        _client.ImportResult = new ImportedSession(meeting.Id, "imported");
        var page = Create();

        await page.ImportCommand.ExecuteAsync(null);
        await page.History.DetailLoading;

        Assert.Equal(("Import a meeting exported by VozAta (.zip)", "ZIP archive", "zip"), _saver.Opens.Single());
        Assert.Equal("PK"u8.ToArray(), _client.Imported.Single());
        Assert.Equal("Meeting imported: Retro.", page.Message);
        Assert.Single(Rows(page));
        Assert.Equal(meeting.Id, page.History.Detail?.Id);
        Assert.False(page.IsImporting);
    }

    [Fact]
    public async Task A_zip_that_brings_the_audio_back_says_so()
    {
        var meeting = Add(NoonClock.Local(2026, 10, 14, 9), 60, "Retro");
        _client.Details[meeting.Id] = Detail(meeting.Id, "Retro");
        _client.ImportResult = new ImportedSession(meeting.Id, "audio_restored");
        var page = Create();

        await page.ImportCommand.ExecuteAsync(null);

        Assert.Equal("Audio restored: Retro.", page.Message);
    }

    [Fact]
    public async Task A_cancelled_import_does_nothing()
    {
        _saver.OpenContent = null;
        var page = Create();

        await page.ImportCommand.ExecuteAsync(null);

        Assert.Empty(_client.Imported);
        Assert.Null(page.Message);
    }

    [Fact]
    public async Task A_refused_import_shows_the_engine_message()
    {
        _client.ImportError = new EngineApiException(HttpStatusCode.Conflict, "session_exists", "Already there.");
        var page = Create();

        await page.ImportCommand.ExecuteAsync(null);

        Assert.Equal("Already there.", page.Error);
        Assert.Null(page.Message);
        Assert.False(page.IsImporting);
    }

    [Fact]
    public async Task An_imported_meeting_that_cannot_be_read_back_still_says_it_was_imported()
    {
        _client.ImportResult = new ImportedSession("20261014_090000", "imported");
        var page = Create();

        await page.ImportCommand.ExecuteAsync(null);

        Assert.Equal("Meeting imported: 20261014_090000.", page.Message);
        Assert.Null(page.History.Detail);
    }

    [Fact]
    public async Task Importing_an_audio_file_sends_it_and_opens_the_new_meeting()
    {
        var meeting = Add(NoonClock.Local(2026, 10, 20, 15), 60, "Weekly sync");
        _client.Details[meeting.Id] = Detail(meeting.Id, "Weekly sync");
        _client.ImportAudioResult = new ImportedAudio(meeting.Id);
        var page = Create();

        await page.ImportAudioCommand.ExecuteAsync(null);
        await page.History.DetailLoading;

        var open = _saver.FileOpens.Single();
        Assert.Equal(("Import an audio or video file", "Audio and video files"), (open.Title, open.TypeName));
        Assert.Contains("mp3", open.Extensions);
        Assert.Contains("m4a", open.Extensions);
        Assert.Contains("mp4", open.Extensions);
        var sent = _client.ImportedAudio.Single();
        Assert.Equal("ID3"u8.ToArray(), sent.Bytes);
        Assert.Equal(("Weekly sync.mp3", _saver.OpenFile!.Value.Modified), (sent.FileName, sent.RecordedAt));
        Assert.Equal("Audio imported: Weekly sync. It is transcribed in the background.", page.Message);
        Assert.Equal(meeting.Id, page.History.Detail?.Id);
        Assert.False(page.IsImporting);
    }

    [Fact]
    public async Task A_cancelled_audio_import_does_nothing()
    {
        _saver.OpenFile = null;
        var page = Create();

        await page.ImportAudioCommand.ExecuteAsync(null);

        Assert.Empty(_client.ImportedAudio);
        Assert.Null(page.Message);
        Assert.False(page.IsImporting);
    }

    [Fact]
    public async Task A_refused_audio_file_shows_the_engine_message()
    {
        _client.ImportAudioError = new EngineApiException(HttpStatusCode.UnprocessableEntity, "audio_invalid", "No audio.");
        var page = Create();

        await page.ImportAudioCommand.ExecuteAsync(null);

        Assert.Equal("No audio.", page.Error);
        Assert.Null(page.Message);
        Assert.False(page.IsImporting);
    }

    [Fact]
    public async Task An_imported_audio_file_that_cannot_be_read_back_names_its_id()
    {
        _client.ImportAudioResult = new ImportedAudio("20261020_152958");
        var page = Create();

        await page.ImportAudioCommand.ExecuteAsync(null);

        Assert.Equal("Audio imported: 20261020_152958. It is transcribed in the background.", page.Message);
        Assert.Null(page.History.Detail);
    }

    private static SessionDetail Detail(string id, string title) =>
        new(id, "done", NoonClock.Local(2026, 10, 14, 9), null, 60, "en", false, null, null)
        {
            Metadata = new Dictionary<string, JsonElement> { ["title"] = JsonSerializer.SerializeToElement(title) },
        };

    // Background processing (phase 40)

    private readonly ProcessingMarkers _markers = new();

    private MeetingsPageViewModel CreateWithMarkers()
    {
        var history = new HistoryViewModel(_client, _shell, _localization, _saver, dialogs: _dialogs, markers: _markers);
        return new MeetingsPageViewModel(_client, history, _localization, _clock, _dialogs, _shell, _saver, markers: _markers);
    }

    private SessionSummary AddProcessing(DateTimeOffset start, ProcessingInfo? info, string status = "done")
    {
        var summary = Add(start, 60, status: status) with { Processing = info };
        _client.Sessions[^1] = summary;
        return summary;
    }

    [Fact]
    public async Task Row_shows_queued_position()
    {
        var queued = AddProcessing(NoonClock.Local(2026, 10, 14, 9), new ProcessingInfo("queued", 0, null, 2));
        var page = CreateWithMarkers();

        await page.LoadAsync();

        var row = Rows(page).Single();
        Assert.Equal(queued.Id, row.Id);
        Assert.Equal(("Queued (2)", true, false), (row.ProcessingText, row.IsProcessing, row.ShowsDoneCheck));
        Assert.False(row.IsLive);
    }

    [Fact]
    public async Task Row_percent_follows_events()
    {
        var running = AddProcessing(NoonClock.Local(2026, 10, 14, 9), new ProcessingInfo("queued", 0, null, 1));
        var page = CreateWithMarkers();
        await page.LoadAsync();
        var row = Rows(page).Single();

        await page.OnProcessingAsync(new ProcessingEvent(running.Id, new ProcessingInfo("running", 42, "transcribe")));
        Assert.Equal(("Processing 42 %", true), (row.ProcessingText, row.IsProcessing));

        await page.OnProcessingAsync(new ProcessingEvent(running.Id, new ProcessingInfo("paused", 42, "transcribe")));
        Assert.Equal("Paused", row.ProcessingText);

        await page.OnProcessingAsync(new ProcessingEvent(running.Id, new ProcessingInfo("running", 77, "diarize")));
        Assert.Equal("Processing 77 %", row.ProcessingText);

        await page.OnProcessingAsync(new ProcessingEvent("another", new ProcessingInfo("running", 5, "repair")));
        Assert.Equal("Processing 77 %", row.ProcessingText); // not ours

        _localization.SetLanguage("pt-BR");
        page.RefreshTexts();
        try
        {
            Assert.Equal("Processando 77 %", Rows(page).Single().ProcessingText); // survives a re-render
        }
        finally
        {
            _localization.SetLanguage("en");
        }

        _client.Sessions[0] = running with { Processing = null }; // the engine dropped it
        await page.OnProcessingAsync(new ProcessingEvent(running.Id, new ProcessingInfo("failed", 77, "diarize")));
        var after = Rows(page).Single();
        Assert.Equal((false, false), (after.IsProcessing, after.ShowsDoneCheck)); // the error toast tells the rest
    }

    [Fact]
    public async Task Row_done_shows_green_check_without_percent_until_opened()
    {
        var meeting = AddProcessing(NoonClock.Local(2026, 10, 14, 9), new ProcessingInfo("running", 90, "index"));
        _client.Details[meeting.Id] = new SessionDetail(meeting.Id, "done", null, null, 60, "en", false, [], @"C:\rec");
        var page = CreateWithMarkers();
        await page.LoadAsync();

        _client.Sessions[0] = meeting with { Processing = null, SpeakerCount = 2 }; // the engine finished it
        await page.OnProcessingAsync(new ProcessingEvent(meeting.Id, new ProcessingInfo("done", 100, null)));

        var row = Rows(page).Single();
        Assert.Equal((true, false, "Ready", 2), (row.ShowsDoneCheck, row.IsProcessing, row.DoneText, row.SpeakerCount));
        Assert.True(_markers.IsUnseen(meeting.Id));

        await page.LoadAsync(); // reloads keep the check
        Assert.True(Rows(page).Single().ShowsDoneCheck);

        page.OpenCommand.Execute(Rows(page).Single());
        await page.History.DetailLoading;
        Assert.False(Rows(page).Single().ShowsDoneCheck);
        Assert.False(_markers.IsUnseen(meeting.Id));
    }

    [Fact]
    public async Task Opening_meeting_clears_unseen_marker()
    {
        var meeting = AddProcessing(NoonClock.Local(2026, 10, 14, 9), null);
        _client.Details[meeting.Id] = new SessionDetail(meeting.Id, "done", null, null, 60, "en", false, [], @"C:\rec");
        _markers.MarkDone(meeting.Id);
        var page = CreateWithMarkers();
        await page.LoadAsync();
        Assert.True(Rows(page).Single().ShowsDoneCheck);

        page.OpenCommand.Execute(Rows(page).Single());
        await page.History.DetailLoading;

        Assert.False(_markers.IsUnseen(meeting.Id));
        Assert.False(Rows(page).Single().ShowsDoneCheck);
    }

    [Fact]
    public async Task A_meeting_that_finishes_while_open_is_not_marked_unseen()
    {
        var meeting = AddProcessing(NoonClock.Local(2026, 10, 14, 9), new ProcessingInfo("running", 90, "index"));
        _client.Details[meeting.Id] = new SessionDetail(meeting.Id, "done", null, null, 60, "en", false, [], @"C:\rec");
        var page = CreateWithMarkers();
        await page.LoadAsync();
        page.OpenCommand.Execute(Rows(page).Single());
        await page.History.DetailLoading;

        _client.Sessions[0] = meeting with { Processing = null };
        await page.OnProcessingAsync(new ProcessingEvent(meeting.Id, new ProcessingInfo("done", 100, null)));

        Assert.False(_markers.IsUnseen(meeting.Id));
        Assert.False(Rows(page).Single().ShowsDoneCheck);
    }

    [Fact]
    public async Task Status_done_of_a_background_meeting_refreshes_its_row()
    {
        var meeting = AddProcessing(NoonClock.Local(2026, 10, 14, 9), new ProcessingInfo("running", 99, "index"), status: "finalizing");
        var page = CreateWithMarkers();
        await page.LoadAsync();
        Assert.Null(page.Live);

        _client.Sessions[0] = meeting with { Status = "done", Processing = null, SpeakerCount = 3 };
        await page.OnSessionDoneAsync(meeting.Id);

        Assert.Equal(3, Rows(page).Single().SpeakerCount);
    }

    [Fact]
    public async Task An_event_received_while_the_list_loads_is_not_lost()
    {
        var meeting = AddProcessing(NoonClock.Local(2026, 10, 14, 9), new ProcessingInfo("queued", 0, null, 1), status: "finalizing");
        var page = CreateWithMarkers();
        await page.LoadAsync();
        _client.DaysGate = new TaskCompletionSource();

        var loading = page.LoadAsync(); // the list was read before the event below
        await page.OnProcessingAsync(new ProcessingEvent(meeting.Id, new ProcessingInfo("running", 50, "transcribe")));
        _client.DaysGate.SetResult();
        await loading;

        Assert.Equal("Processing 50 %", Rows(page).Single().ProcessingText);
        _client.DaysGate = null;
        _client.Sessions[0] = meeting with { Processing = new ProcessingInfo("running", 60, "mix") };
        await page.LoadAsync(); // a list requested after the event is the truth again
        Assert.Equal("Processing 60 %", Rows(page).Single().ProcessingText);
    }

    [Fact]
    public async Task A_finished_meeting_is_not_shown_processing_by_a_list_read_before_it_finished()
    {
        var meeting = AddProcessing(NoonClock.Local(2026, 10, 14, 9), new ProcessingInfo("running", 99, "index"), status: "finalizing");
        var page = CreateWithMarkers();
        await page.LoadAsync();
        _client.DaysGate = new TaskCompletionSource();

        var loading = page.LoadAsync(); // asked while it still ran: stale
        _client.Sessions[0] = meeting with { Status = "done", Processing = null, SpeakerCount = 2 };
        var done = page.OnSessionDoneAsync(meeting.Id);
        _client.DaysGate.SetResult();
        await Task.WhenAll(loading, done);

        var row = Rows(page).Single();
        Assert.Equal((false, 2), (row.IsProcessing, row.SpeakerCount));
    }

    [Fact]
    public async Task A_list_answered_after_a_newer_one_is_ignored()
    {
        var meeting = AddProcessing(NoonClock.Local(2026, 10, 14, 9), new ProcessingInfo("running", 99, "index"), status: "finalizing");
        var page = CreateWithMarkers();
        await page.LoadAsync();
        var (older, newer) = (new TaskCompletionSource(), new TaskCompletionSource());
        _client.DaysGates = new Queue<TaskCompletionSource>([older, newer]);

        var stale = page.LoadAsync();
        _client.Sessions[0] = meeting with { Status = "done", Processing = null, SpeakerCount = 2 };
        var fresh = page.LoadAsync();
        newer.SetResult();
        await fresh;
        older.SetResult();
        await stale;

        Assert.Equal((false, 2), (Rows(page).Single().IsProcessing, Rows(page).Single().SpeakerCount));
        Assert.False(page.IsLoading);
    }

    [Fact]
    public async Task Connection_loss_clears_the_badges_until_the_snapshot_rebuilds_them()
    {
        var meeting = AddProcessing(NoonClock.Local(2026, 10, 14, 9), new ProcessingInfo("queued", 0, null, 1), status: "finalizing");
        var other = AddProcessing(NoonClock.Local(2026, 10, 15, 9), null);
        var page = CreateWithMarkers();
        await page.LoadAsync();
        await page.OnProcessingAsync(new ProcessingEvent(meeting.Id, new ProcessingInfo("running", 30, "transcribe")));

        page.OnConnectionLost();

        Assert.All(Rows(page), row => Assert.False(row.IsProcessing));
        page.RefreshTexts(); // a re-render does not bring the stale summary back
        Assert.All(Rows(page), row => Assert.False(row.IsProcessing));
        await page.OnProcessingAsync(new ProcessingEvent(meeting.Id, new ProcessingInfo("running", 35, "transcribe"))); // snapshot
        Assert.Equal("Processing 35 %", Rows(page).Single(row => row.Id == meeting.Id).ProcessingText);
        Assert.False(Rows(page).Single(row => row.Id == other.Id).IsProcessing);
    }

    [Fact]
    public async Task Finalizing_row_is_not_pinned_as_live()
    {
        Add(NoonClock.Local(2026, 10, 14, 9), 60, status: "finalizing");
        Add(NoonClock.Local(2026, 10, 15, 9), 60, status: "recording");
        var page = CreateWithMarkers();

        await page.LoadAsync();

        Assert.Equal("20261015_090000", page.Live?.Id);
        var finalizing = Rows(page).Single();
        Assert.Equal(("20261014_090000", false, false), (finalizing.Id, finalizing.IsLive, finalizing.CanDelete)); // not deletable while it finishes
    }
}
