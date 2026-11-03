using System.Net;
using System.Text.Json;
using VozAta.Client;
using VozAta.Desktop.Tests.Fakes;

namespace VozAta.Desktop.Tests;

/// <summary>The recorder process API client and its event stream (phase 61).</summary>
public sealed class RecorderClientTests
{
    private const string Summary = """{"id":"20261103_101500","status":"recording","started_at":"2026-11-03T10:15:00-03:00","duration_seconds":12.5,"options":{"title":"Weekly"}}""";

    [Fact]
    public async Task Start_sends_the_devices_and_the_options_and_reads_the_summary()
    {
        var handler = FakeHttpHandler.Json(Summary);
        var client = new RecorderClient(handler.Client());

        var started = await client.StartAsync(new StartRecordingRequest(
            15, null, new Dictionary<string, object?> { ["language"] = "pt", ["live_transcription"] = true }));

        var (method, path, body) = handler.Requests.Single();
        Assert.Equal((HttpMethod.Post, "/recordings"), (method, path));
        using var sent = JsonDocument.Parse(body!);
        Assert.Equal(15, sent.RootElement.GetProperty("mic_device_id").GetInt32());
        Assert.Equal("pt", sent.RootElement.GetProperty("options").GetProperty("language").GetString());
        Assert.True(sent.RootElement.GetProperty("options").GetProperty("live_transcription").GetBoolean());
        Assert.Equal("20261103_101500", started.Id);
        Assert.Equal(12.5, started.DurationSeconds);
        Assert.True(started.IsActive);
        Assert.Equal("Weekly", started.Options!["title"].GetString());
    }

    [Fact]
    public async Task The_controls_and_options_hit_their_routes()
    {
        var handler = FakeHttpHandler.Json(Summary);
        var client = new RecorderClient(handler.Client());

        await client.GetHealthAsync().ContinueWith(_ => { }, TaskScheduler.Default); // not the shape: ignored
        await client.PauseAsync();
        await client.ResumeAsync();
        await client.StopAsync();
        await client.UpdateOptionsAsync(new Dictionary<string, object?> { ["title"] = "A" });
        await client.GetDevicesAsync().ContinueWith(_ => { }, TaskScheduler.Default);

        Assert.Equal(
            ["/health", "/recordings/current/pause", "/recordings/current/resume", "/recordings/current/stop",
             "/recordings/current", "/devices"],
            handler.Requests.Select(request => request.Path));
        Assert.Equal(HttpMethod.Patch, handler.Requests[4].Method);
        Assert.Contains("\"options\":{\"title\":\"A\"}", handler.Requests[4].Body);
    }

    [Fact]
    public async Task Recorder_errors_become_engine_exceptions()
    {
        var handler = FakeHttpHandler.Json(
            """{"error":{"code":"recording_already_active","message":"A recording is in progress"}}""", HttpStatusCode.Conflict);
        var client = new RecorderClient(handler.Client());

        var error = await Assert.ThrowsAsync<EngineApiException>(() => client.StopAsync());

        Assert.Equal(("recording_already_active", "A recording is in progress"), (error.Code, error.Message));
    }

    [Fact]
    public async Task A_page_that_is_not_the_envelope_is_a_generic_error()
    {
        var handler = FakeHttpHandler.Json("<html>", HttpStatusCode.BadGateway);

        var error = await Assert.ThrowsAsync<EngineApiException>(() => new RecorderClient(handler.Client()).PauseAsync());

        Assert.Equal("http_error", error.Code);
    }

    [Fact]
    public async Task A_recorder_that_does_not_answer_is_unavailable()
    {
        var handler = new FakeHttpHandler(_ => throw new HttpRequestException("refused"));

        await Assert.ThrowsAsync<EngineUnavailableException>(() => new RecorderClient(handler.Client()).GetHealthAsync());
    }

    [Theory]
    [InlineData("status", """{"id":null,"status":"idle","duration_seconds":0}""", "idle")]
    [InlineData("level", """{"channel":"mic","rms_db":-12.5}""", "level")]
    [InlineData("error", """{"code":"disk_backlog","message":"40 s wait"}""", "error")]
    public void Events_are_parsed(string name, string data, string kind)
    {
        var parsed = RecorderEventParser.Parse(name, data);

        switch (kind)
        {
            case "idle":
                Assert.False(Assert.IsType<RecorderStatusEvent>(parsed).Recording.IsActive);
                break;
            case "level":
                Assert.Equal(new RecorderLevelEvent("mic", -12.5), parsed);
                break;
            default:
                Assert.Equal(new RecorderErrorEvent("disk_backlog", "40 s wait"), parsed);
                break;
        }
    }

    [Theory]
    [InlineData("unknown", "{}")]
    [InlineData("level", "{broken")]
    public void Unknown_or_broken_events_are_skipped(string name, string data) =>
        Assert.Null(RecorderEventParser.Parse(name, data));

    [Fact]
    public async Task The_stream_reports_connections_events_and_reconnects()
    {
        var source = new ScriptedSource(
            null, // the recorder is not up yet
            "event: status\ndata: {\"id\":\"r1\",\"status\":\"recording\",\"duration_seconds\":1}\n\n"
            + ": keep-alive\n\nevent: level\ndata: {\"channel\":\"system\",\"rms_db\":-30}\n\n",
            null,
            "event: error\ndata: {\"code\":\"write_failed\",\"message\":\"disk\"}\n\n");
        using var stop = new CancellationTokenSource();
        var events = new RecorderEvents(source, (wait, token) => Task.CompletedTask);
        var seen = new List<RecorderEvent>();

        await foreach (var recorderEvent in events.ReadAllAsync(stop.Token))
        {
            seen.Add(recorderEvent);
            if (recorderEvent is RecorderErrorEvent)
            {
                stop.Cancel();
            }
        }

        Assert.Equal(
            ["Connection:False", "Connection:True", "Status:r1", "Level:system", "Connection:False",
             "Connection:True", "Error:write_failed"],
            seen.Select(Describe));
    }

    private static string Describe(RecorderEvent recorderEvent) => recorderEvent switch
    {
        RecorderConnectionChangedEvent connection => $"Connection:{connection.Connected}",
        RecorderStatusEvent status => $"Status:{status.Recording.Id}",
        RecorderLevelEvent level => $"Level:{level.Channel}",
        RecorderErrorEvent error => $"Error:{error.Code}",
        _ => "?",
    };

    /// <summary>Each open returns the next script (null = the recorder does not answer).</summary>
    private sealed class ScriptedSource(params string?[] scripts) : IEventStreamSource
    {
        private int _next;

        public Task<TextReader> OpenAsync(CancellationToken cancellationToken)
        {
            var script = _next < scripts.Length ? scripts[_next] : null;
            _next++;
            return script is null
                ? Task.FromException<TextReader>(new HttpRequestException("refused"))
                : Task.FromResult<TextReader>(new StringReader(script));
        }
    }
}
