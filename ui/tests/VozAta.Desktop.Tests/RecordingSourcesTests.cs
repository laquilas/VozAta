using System.Net;
using System.Text.Json;
using VozAta.Client;
using VozAta.Desktop.Services;
using VozAta.Desktop.Tests.Fakes;
using VozAta.Desktop.ViewModels;

namespace VozAta.Desktop.Tests;

/// <summary>Every audio source of a recording (phase 65): client, event, list and modes.</summary>
public sealed class RecordingSourcesTests
{
    private const string Id = "20261103_101500";

    private const string SourcesJson = """
        {"id":"20261103_101500","items":[
          {"id":"in-jbl","kind":"mic","name":"Microfone (JBL)","mode":"auto","selected":true,"preferred":true,
           "state":"open","error":null,"rms_db":-30.0,"score":0.4,"silent":false},
          {"id":"out-realtek","kind":"system","name":"Alto-falantes (Realtek) [Loopback]","mode":"off","selected":false,
           "preferred":false,"state":"failed","error":"busy","rms_db":-90.0,"score":0.0,"silent":true}]}
        """;

    private readonly FakeEngineClient _engine = new();
    private readonly FakeRecorderClient _recorder = new();
    private readonly LocalizationService _localization = new();
    private readonly List<string> _notified = [];

    private static RecordingSource Source(string id, string kind = "mic", bool selected = false, bool silent = false) =>
        new(id, kind, id.ToUpperInvariant(), Selected: selected, Silent: silent);

    [Fact]
    public async Task The_client_reads_the_sources_and_sets_a_mode()
    {
        var handler = FakeHttpHandler.Json(SourcesJson);
        var client = new RecorderClient(handler.Client());

        var sources = await client.GetSourcesAsync();
        await client.SetSourceModeAsync("in-jbl", "on");

        Assert.Equal(["in-jbl", "out-realtek"], sources.Items.Select(item => item.Id));
        Assert.Equal(("system", "failed", "busy", true), (sources.Items[1].Kind, sources.Items[1].State, sources.Items[1].Error, sources.Items[1].Silent));
        Assert.Equal(-30.0, sources.Items[0].RmsDb);
        Assert.Equal((HttpMethod.Get, "/recordings/current/sources"), (handler.Requests[0].Method, handler.Requests[0].Path));
        Assert.Equal((HttpMethod.Put, "/recordings/current/sources/in-jbl"), (handler.Requests[1].Method, handler.Requests[1].Path));
        using var body = JsonDocument.Parse(handler.Requests[1].Body!);
        Assert.Equal("on", body.RootElement.GetProperty("mode").GetString());
    }

    [Fact]
    public void The_sources_event_is_parsed_and_a_broken_one_ignored()
    {
        var parsed = Assert.IsType<RecorderSourcesEvent>(RecorderEventParser.Parse("sources", SourcesJson));

        Assert.Equal(Id, parsed.Sources.Id);
        Assert.Equal(2, parsed.Sources.Items.Count);
        Assert.Null(RecorderEventParser.Parse("sources", "{\"id\":null}"));
        Assert.Null(RecorderEventParser.Parse("sources", "{broken"));
    }

    [Fact]
    public void Update_keeps_the_rows_by_id_and_describes_them()
    {
        var sources = new RecordingSourcesViewModel(_recorder, _localization, _notified.Add);
        sources.Update(new RecordingSources(Id, [Source("in-a", selected: true), Source("out-b", "system")]));
        var first = sources.Items[0];

        sources.Update(new RecordingSources(Id,
        [
            Source("in-c", silent: true), Source("in-a", selected: false), Source("out-b", "system", selected: true),
        ]));

        Assert.Equal(["in-c", "in-a", "out-b"], sources.Items.Select(row => row.Id));
        Assert.Same(first, sources.Items[1]);
        Assert.False(first.IsSelected);
        Assert.True(sources.HasItems);
        Assert.Equal(_localization.Format("SourcesSummary", 1, 3), sources.Summary);
        Assert.Equal(_localization["SourceSilent"], sources.Items[0].StatusText);
        Assert.Equal(_localization["SourceNotInUse"], first.StatusText);
        Assert.Equal(_localization["SourceInUse"], sources.Items[2].StatusText);
        Assert.True(sources.Items[2].IsOutput);
        Assert.Equal(_localization["SourceKindOutput"], sources.Items[2].KindText);
        Assert.False(sources.AllSilent);

        sources.Update(new RecordingSources(Id, [Source("in-c", silent: true)]));

        Assert.True(sources.AllSilent);
        sources.Clear();
        Assert.False(sources.HasItems);
    }

    [Fact]
    public void A_failed_source_says_why_and_does_not_count_for_silence()
    {
        var sources = new RecordingSourcesViewModel(_recorder, _localization, _notified.Add);

        sources.Update(new RecordingSources(Id, [Source("in-a") with { State = "failed", Error = "busy", Silent = true }]));

        Assert.True(sources.Items[0].HasFailed);
        Assert.Equal(_localization.Format("SourceFailed", "busy"), sources.Items[0].StatusText);
        Assert.False(sources.AllSilent);
    }

    [Fact]
    public async Task A_mode_goes_to_the_recorder_and_its_answer_updates_the_rows()
    {
        _recorder.SourceItems.Add(Source("in-a"));
        var sources = new RecordingSourcesViewModel(_recorder, _localization, _notified.Add);
        sources.Update(await _recorder.GetSourcesAsync());
        var row = sources.Items[0];

        await row.SetOnCommand.ExecuteAsync(null);

        Assert.Equal(("in-a", "on"), _recorder.ModeChanges.Single());
        Assert.True(row.IsOn && row.IsSelected && !row.IsAuto && !row.IsOff);
        await row.SetOffCommand.ExecuteAsync(null);
        await row.SetAutoCommand.ExecuteAsync(null);
        Assert.Equal(["on", "off", "auto"], _recorder.ModeChanges.Select(change => change.Mode));
    }

    [Fact]
    public async Task A_mode_the_recorder_refuses_is_reported()
    {
        _recorder.SourcesError = new EngineApiException(HttpStatusCode.NotFound, "source_not_found", "No source in-a");
        var sources = new RecordingSourcesViewModel(_recorder, _localization, _notified.Add);
        sources.Update(new RecordingSources(Id, [Source("in-a")]));

        await sources.Items[0].SetOffCommand.ExecuteAsync(null);

        Assert.Equal(_localization.Format("SourceModeFailed", "IN-A", "No source in-a"), _notified.Single());
    }

    [Fact]
    public async Task Without_a_recorder_a_mode_does_nothing()
    {
        var sources = new RecordingSourcesViewModel(null, _localization, _notified.Add);
        sources.Update(new RecordingSources(Id, [Source("in-a")]));

        await sources.Items[0].SetOnCommand.ExecuteAsync(null);

        Assert.Empty(_notified);
    }

    [Fact]
    public void A_language_change_refreshes_the_texts()
    {
        var sources = new RecordingSourcesViewModel(_recorder, _localization, _notified.Add);
        sources.Update(new RecordingSources(Id, [Source("in-a", selected: true)]));

        _localization.SetLanguage("pt-BR");
        sources.RefreshTexts();

        Assert.Equal("Em uso", sources.Items[0].StatusText);
        Assert.Equal("Ligado", sources.Items[0].OnText);
        Assert.Equal("1 de 1 em uso", sources.Summary);
        _localization.SetLanguage("en");
    }

    private RecorderPageViewModel Page() =>
        new(_engine, _localization, new FakePreferences(), new FakeClock(), new FakeTimer(),
            new MinutesTemplatesViewModel(_engine), new RecordingSessionService(), _notified.Add,
            recorder: _recorder)
        {
            IsRecorderConnected = true,
        };

    [Fact]
    public async Task The_page_shows_the_sources_of_its_recording_and_clears_them_at_stop()
    {
        var page = Page();
        var sources = new RecordingSources(Id, [Source("in-a", selected: true)]);
        Assert.True(page.HandleRecorder(new RecorderSourcesEvent(sources)));
        Assert.False(page.Sources.HasItems); // not recording through the recorder yet

        await page.StartCommand.ExecuteAsync(null);
        page.HandleRecorder(new RecorderSourcesEvent(sources));
        Assert.True(page.Sources.HasItems);

        page.HandleRecorder(new RecorderStatusEvent(new RecordingSummary(Id, "stopped")));
        Assert.False(page.Sources.HasItems);
    }

    [Fact]
    public void The_page_explains_the_source_problems()
    {
        var page = Page();

        page.HandleRecorder(new RecorderErrorEvent("all_sources_silent", "Every audio device gives only silence"));
        page.HandleRecorder(new RecorderErrorEvent("source_failed", "Microfone (Sala 2): busy"));

        Assert.Equal(
            [_localization["SourcesAllSilentNotice"], _localization.Format("SourceFailedNotice", "Microfone (Sala 2): busy")],
            _notified);
    }
}
