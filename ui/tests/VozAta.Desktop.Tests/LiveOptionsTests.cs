using VozAta.Client;
using VozAta.Desktop.Services;
using VozAta.Desktop.Tests.Fakes;
using VozAta.Desktop.ViewModels;

namespace VozAta.Desktop.Tests;

/// <summary>The chips change the meeting being recorded (phase 63).</summary>
public sealed class LiveOptionsTests
{
    private const string Id = "20261103_101500";

    private readonly FakeEngineClient _engine = new();
    private readonly FakeRecorderClient _recorder = new();
    private readonly ManualDelay _delay = new();
    private readonly List<string> _notified = [];
    private readonly RecordingSessionService _session = new();

    private RecorderPageViewModel Create(bool viaRecorder, bool engine = true) =>
        new(_engine, new LocalizationService(), new FakePreferences(), new FakeClock(), new FakeTimer(),
            new MinutesTemplatesViewModel(_engine), _session, _notified.Add, titleDelay: _delay.Wait,
            recorder: _recorder)
        {
            IsEngineConnected = engine,
            IsRecorderConnected = viaRecorder,
        };

    private async Task<RecorderPageViewModel> RecordingAsync(bool viaRecorder, bool engine = true)
    {
        var page = Create(viaRecorder, engine);
        await page.LoadTemplatesAsync();
        await page.StartCommand.ExecuteAsync(null);
        return page;
    }

    private async Task SendAsync(RecorderPageViewModel page)
    {
        _delay.Elapse();
        await page.OptionsSave;
    }

    [Fact]
    public async Task Changes_while_recording_go_to_the_meeting_and_to_the_recording()
    {
        var page = await RecordingAsync(viaRecorder: true);

        page.SelectedLanguage = page.ConversationLanguages.Single(o => o.Value == "pt");
        page.SessionTerms = "VozAta";
        page.SelectedTemplate = page.Templates.Find("daily");
        await SendAsync(page);

        var (id, changes) = _engine.SessionUpdates.Single();
        Assert.Equal(Id, id);
        Assert.Equal("pt", changes["language"]);
        Assert.Equal(["VozAta"], (IEnumerable<string>)changes["vocabulary"]!);
        Assert.Equal("daily", changes["template"]);
        Assert.Equal("pt", _recorder.OptionUpdates.Single()["language"]);
    }

    [Fact]
    public async Task Before_the_engine_attached_the_recording_keeps_them()
    {
        var page = await RecordingAsync(viaRecorder: true);
        _engine.SessionUpdateError = FakeEngineClient.ApiError("session_not_found", "not yet");

        page.LiveTranscription = false;
        await SendAsync(page);

        Assert.Equal(false, _recorder.OptionUpdates.Single()["live_transcription"]);
        Assert.Empty(_notified);
        Assert.False(page.LiveTranscription);
    }

    [Fact]
    public async Task Without_the_engine_only_the_recording_gets_them()
    {
        var page = await RecordingAsync(viaRecorder: true, engine: false);

        page.SelectedTranslation = page.TranslationLanguages.Single(o => o.Value == "es");
        await SendAsync(page);

        Assert.Equal("es", _recorder.OptionUpdates.Single()["translate_to"]);
        Assert.Empty(_engine.SessionUpdates);
    }

    [Fact]
    public async Task A_refused_change_puts_the_chip_back()
    {
        var page = await RecordingAsync(viaRecorder: false);
        _engine.SessionUpdateError = FakeEngineClient.ApiError("live_transcription_needs_recorder", "needs the recorder");

        page.LiveTranscription = false;
        await SendAsync(page);

        Assert.Equal(["needs the recorder"], _notified);
        Assert.True(page.LiveTranscription); // back to what the meeting has
    }

    [Fact]
    public async Task Idle_changes_are_not_sent()
    {
        var page = Create(viaRecorder: false);

        page.SelectedLanguage = page.ConversationLanguages.Single(o => o.Value == "es");
        await SendAsync(page);

        Assert.Empty(_engine.SessionUpdates);
    }

    [Fact]
    public async Task Another_clients_change_shows_on_the_chips_without_being_sent_back()
    {
        var page = await RecordingAsync(viaRecorder: true);
        var changes = FakeRecorderClient.Options("""{"language":"es","vocabulary":["A","B"],"live_transcription":false}""");

        page.OnSessionUpdated(new SessionUpdatedEvent(Id, changes));
        page.OnSessionUpdated(new SessionUpdatedEvent("other", changes));
        await SendAsync(page);

        Assert.Equal("es", page.SelectedLanguage.Value);
        Assert.Equal("A, B", page.SessionTerms);
        Assert.False(page.LiveTranscription);
        Assert.Empty(_engine.SessionUpdates);
    }

    [Fact]
    public async Task The_update_route_and_the_event_are_parsed()
    {
        var handler = FakeHttpHandler.Json(
            """{"id":"x","status":"recording","started_at":null,"ended_at":null,"duration_seconds":1,"language":null,"has_minutes":false}""");
        await new EngineClient(handler.Client()).UpdateSessionAsync("x", new Dictionary<string, object?> { ["language"] = "pt" });
        var parsed = EngineEventParser.Parse("""{"type":"session_updated","session_id":"x","data":{"language":"pt"}}""");

        var request = handler.Requests.Single();
        Assert.Equal((HttpMethod.Patch, "/sessions/x"), (request.Method, request.Path));
        Assert.Equal("""{"language":"pt"}""", request.Body);
        Assert.Equal("pt", Assert.IsType<SessionUpdatedEvent>(parsed).Changes["language"].GetString());
    }
}
