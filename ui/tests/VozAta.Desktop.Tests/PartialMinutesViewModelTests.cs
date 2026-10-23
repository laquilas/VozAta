using System.Net;
using VozAta.Client;
using VozAta.Desktop.Services;
using VozAta.Desktop.Tests.Fakes;
using VozAta.Desktop.ViewModels;

namespace VozAta.Desktop.Tests;

/// <summary>Minutes so far in the recorder and the meeting page's Partial minutes tab (phase 48).</summary>
public sealed class PartialMinutesViewModelTests
{
    private const string SessionId = "20261016_090000";

    private static readonly PartialMinutesDetail SoFar = new(
        "p1", "2026-10-16T09:12:00-03:00", 0, 754, "button", "general", "# Ata\n\n- Beta na terça\n");

    private static readonly PartialMinutesDetail Part = new(
        "p2", "2026-10-16T10:00:00-03:00", 152, 774, "range", null, "# Trecho\n");

    private readonly FakeEngineClient _client = new();
    private readonly FakeShell _shell = new();
    private readonly LocalizationService _localization = new();
    private readonly List<string> _notified = [];
    private readonly RecordingSessionService _session = new();

    private RecorderPageViewModel Recorder() =>
        new(_client, _localization, new FakePreferences(), new FakeClock(), new FakeTimer(),
            new MinutesTemplatesViewModel(_client), _session, _notified.Add, shell: _shell)
        {
            IsEngineConnected = true,
        };

    [Fact]
    public async Task Minutes_so_far_need_a_recording_with_live_transcription()
    {
        var recorder = Recorder();
        Assert.False(recorder.WriteMinutesSoFarCommand.CanExecute(null));

        await recorder.StartCommand.ExecuteAsync(null);
        Assert.True(recorder.WriteMinutesSoFarCommand.CanExecute(null));

        await recorder.StopCommand.ExecuteAsync(null);
        Assert.False(recorder.WriteMinutesSoFarCommand.CanExecute(null));
    }

    [Fact]
    public async Task An_audio_only_recording_has_no_minutes_so_far()
    {
        var recorder = Recorder();
        recorder.LiveTranscription = false;

        await recorder.StartCommand.ExecuteAsync(null);

        Assert.False(recorder.WriteMinutesSoFarCommand.CanExecute(null));
    }

    [Fact]
    public async Task Asking_waits_for_the_engine_then_shows_the_minutes_beside_the_transcript()
    {
        var recorder = Recorder();
        await recorder.StartCommand.ExecuteAsync(null);

        await recorder.WriteMinutesSoFarCommand.ExecuteAsync(null);

        Assert.Equal([(SessionId, (double?)null, (double?)null, (string?)null)], _client.PartialRequests);
        Assert.True(recorder.MinutesSoFar.IsWriting);
        Assert.False(recorder.WriteMinutesSoFarCommand.CanExecute(null)); // one at a time

        _client.PartialMinutes[SessionId] = [SoFar];
        await recorder.MinutesSoFar.OnReadyAsync(new PartialMinutesReadyEvent(SessionId, "p1", 0, 754, "button"));

        var soFar = recorder.MinutesSoFar;
        Assert.False(soFar.IsWriting);
        Assert.True(soFar.IsOpen);
        Assert.Equal(_localization.Format("MinutesSoFarCaption", "00:12:34"), soFar.Caption);
        Assert.Equal(["Ata", "Beta na terça"], soFar.Blocks.Select(block => block.Text));
        Assert.True(recorder.WriteMinutesSoFarCommand.CanExecute(null));

        await soFar.CopyCommand.ExecuteAsync(null);
        soFar.CloseCommand.Execute(null);

        Assert.Equal(["# Ata\n\n- Beta na terça\n"], _shell.Copied);
        Assert.Contains(_localization["Copied"], _notified);
        Assert.False(soFar.IsOpen);
    }

    [Fact]
    public async Task Other_meetings_and_unasked_minutes_are_ignored()
    {
        var soFar = new MinutesSoFarViewModel(_client, _shell, _localization, _notified.Add);
        await soFar.OnReadyAsync(new PartialMinutesReadyEvent(SessionId, "p1", 0, 1, "range")); // not asked

        await soFar.RequestAsync(SessionId);
        await soFar.OnReadyAsync(new PartialMinutesReadyEvent("other", "p9", 0, 1, "button"));

        Assert.True(soFar.IsWriting);
        Assert.False(soFar.IsOpen);
    }

    [Theory]
    [InlineData("empty_range", false)]
    [InlineData("llm_unreachable", false)]
    [InlineData("partial_minutes_failed", false)]
    [InlineData("translation_failed", true)]
    public async Task A_failure_of_the_request_ends_it(string code, bool stillWriting)
    {
        var soFar = new MinutesSoFarViewModel(_client, _shell, _localization, _notified.Add);
        await soFar.RequestAsync(SessionId);

        soFar.OnError("other", code);
        Assert.True(soFar.IsWriting);
        soFar.OnError(SessionId, code);

        Assert.Equal(stillWriting, soFar.IsWriting);
    }

    [Fact]
    public async Task A_refused_request_is_a_notification()
    {
        _client.PartialMinutesError = new EngineApiException(
            HttpStatusCode.Conflict, "partial_minutes_in_progress", "Partial minutes are already being written.");
        var soFar = new MinutesSoFarViewModel(_client, _shell, _localization, _notified.Add);

        await soFar.RequestAsync(SessionId);

        Assert.False(soFar.IsWriting);
        Assert.Equal(["Partial minutes are already being written."], _notified);
    }

    [Fact]
    public async Task Minutes_that_cannot_be_read_end_the_request()
    {
        var soFar = new MinutesSoFarViewModel(_client, null, _localization, _notified.Add);
        await soFar.RequestAsync(SessionId);

        await soFar.OnReadyAsync(new PartialMinutesReadyEvent(SessionId, "missing", 0, 1, "button"));
        await soFar.CopyCommand.ExecuteAsync(null); // no clipboard: nothing happens

        Assert.False(soFar.IsWriting);
        Assert.Equal(["Not found."], _notified);
    }

    private PartialMinutesListViewModel List() => new(_client, _shell, _localization, SessionId);

    [Fact]
    public async Task The_tab_lists_them_and_shows_the_newest()
    {
        _client.PartialMinutes[SessionId] = [SoFar, Part];
        var list = List();

        await list.LoadAsync();

        Assert.True(list.HasItems);
        Assert.Equal(
            [$"{_localization["PartialOrigin_button"]} · 00:00:00 – 00:12:34", $"{_localization["PartialOrigin_range"]} · 00:02:32 – 00:12:54"],
            list.Items.Select(row => row.Title));
        Assert.Same(list.Items[1], list.Selected);
        await WaitForAsync(() => list.Blocks.Count > 0);
        Assert.Equal(["Trecho"], list.Blocks.Select(block => block.Text));
    }

    [Fact]
    public async Task A_new_one_of_this_meeting_is_selected_when_it_arrives()
    {
        _client.PartialMinutes[SessionId] = [Part];
        var list = List();
        await list.LoadAsync();

        _client.PartialMinutes[SessionId].Add(SoFar);
        await list.OnReadyAsync(new PartialMinutesReadyEvent("other", "x", 0, 1, "range"));
        Assert.Single(list.Items);
        await list.OnReadyAsync(new PartialMinutesReadyEvent(SessionId, "p1", 0, 754, "button"));

        Assert.Equal("p1", list.Selected?.Summary.Id);
    }

    [Fact]
    public async Task Copy_and_delete_act_on_the_selected_one()
    {
        _client.PartialMinutes[SessionId] = [SoFar, Part];
        var list = List();
        await list.LoadAsync();
        list.Selected = list.Items[0];
        await WaitForAsync(() => list.Blocks.Count > 0 && list.Blocks[0].Text == "Ata");

        await list.CopyCommand.ExecuteAsync(null);
        await list.DeleteCommand.ExecuteAsync(null);

        Assert.Equal(["# Ata\n\n- Beta na terça\n"], _shell.Copied);
        Assert.Equal(["p2"], list.Items.Select(row => row.Summary.Id));
        Assert.Equal("p2", list.Selected?.Summary.Id);
    }

    [Fact]
    public async Task Without_any_the_tab_says_how_to_get_one()
    {
        var list = List();

        await list.LoadAsync();

        Assert.False(list.HasItems);
        Assert.False(list.HasSelection);
        Assert.False(list.CopyCommand.CanExecute(null));
    }

    private static async Task WaitForAsync(Func<bool> condition)
    {
        for (var i = 0; i < 200 && !condition(); i++)
        {
            await Task.Delay(5);
        }

        Assert.True(condition());
    }
}
