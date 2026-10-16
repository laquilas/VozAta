using System.Net;
using VozAta.Client;
using VozAta.Desktop.Tests.Fakes;

namespace VozAta.Desktop.Tests;

public sealed class EngineClientTests
{
    private const string Summary = """
        {"id": "20261015_202358", "status": "recording", "started_at": "2026-10-15T20:23:58-03:00",
         "ended_at": null, "duration_seconds": 1.5, "language": "pt", "has_minutes": false}
        """;

    [Fact]
    public async Task Health_maps_snake_case_fields()
    {
        var handler = FakeHttpHandler.Json("""
            {"engine": "ok", "version": "0.1.0",
             "gpu": {"available": true, "name": "RTX 3050", "vram_total_mb": 6144},
             "stt": {"provider": "faster_whisper", "model": "large-v3", "device": "auto"},
             "llm": {"provider": "ollama", "model": "qwen2.5:7b", "reachable": false}}
            """);

        var health = await new EngineClient(handler.Client()).GetHealthAsync();

        Assert.Equal(new GpuStatus(true, "RTX 3050", 6144), health.Gpu);
        Assert.Equal("large-v3", health.Stt.Model);
        Assert.False(health.Llm.Reachable);
        Assert.Equal((HttpMethod.Get, "/health", (string?)null), handler.Requests.Single());
    }

    [Fact]
    public async Task Start_sends_a_snake_case_body_and_reads_the_summary()
    {
        var handler = FakeHttpHandler.Json(Summary, HttpStatusCode.Created);

        var summary = await new EngineClient(handler.Client())
            .StartSessionAsync(new StartSessionRequest(MicDeviceId: 9, Language: "pt"));

        var (method, path, body) = handler.Requests.Single();
        Assert.Equal(HttpMethod.Post, method);
        Assert.Equal("/sessions", path);
        Assert.Equal("""{"mic_device_id":9,"system_device_id":null,"language":"pt"}""", body);
        Assert.Equal("20261015_202358", summary.Id);
        Assert.Equal(new DateTimeOffset(2026, 10, 15, 20, 23, 58, TimeSpan.FromHours(-3)), summary.StartedAt);
        Assert.Null(summary.EndedAt);
        Assert.Equal(1.5, summary.DurationSeconds);
    }

    [Fact]
    public async Task Lifecycle_commands_post_to_the_current_session()
    {
        var handler = FakeHttpHandler.Json(Summary);
        var client = new EngineClient(handler.Client());

        await client.PauseSessionAsync();
        await client.ResumeSessionAsync();
        await client.StopSessionAsync();
        await client.RegenerateMinutesAsync("20261015_202358");

        Assert.Equal(
            ["/sessions/current/pause", "/sessions/current/resume", "/sessions/current/stop",
             "/sessions/20261015_202358/minutes"],
            handler.Requests.Select(request => request.Path));
        Assert.All(handler.Requests, request => Assert.Equal(HttpMethod.Post, request.Method));
    }

    [Fact]
    public async Task Sessions_devices_transcript_minutes_and_settings_are_read()
    {
        var handler = new FakeHttpHandler(request => Respond(request.RequestUri!.AbsolutePath switch
        {
            "/sessions" => $$"""{"items": [{{Summary}}], "total": 7}""",
            "/devices" => """
                {"inputs": [{"id": 9, "name": "Mic", "sample_rate": 48000, "channels": 2}],
                 "loopbacks": [], "default_input_id": 9, "default_loopback_id": null}
                """,
            "/sessions/20261015_202358" => """
                {"id": "20261015_202358", "status": "done", "started_at": null, "ended_at": null,
                 "duration_seconds": null, "language": null, "has_minutes": true,
                 "files": ["mic.wav"], "folder": "C:\\rec\\20261015_202358",
                 "devices": {"mic": "Mic"}}
                """,
            "/sessions/20261015_202358/transcript" => """
                {"source": "raw", "segments": [{"segment_id": "mic-000001", "channel": "mic",
                 "speaker_id": "mic", "label": "Me", "start": 1.0, "end": 2.0, "text": "Oi.",
                 "edited": false, "words": [{"text": "Oi.", "start": 1.0, "end": 2.0, "probability": 0.9}]}]}
                """,
            "/sessions/20261015_202358/minutes" => """{"markdown": "# Ata"}""",
            "/settings" => """
                {"values": {"MIX_MODE": "mono", "CHUNK_SECONDS": 5.0, "MIC_LABEL": null},
                 "schema": [{"key": "MIX_MODE", "type": "choice", "default": "mono",
                             "choices": ["mono", "stereo"], "secret": false}]}
                """,
            _ => throw new InvalidOperationException(request.RequestUri.ToString()),
        }));
        var client = new EngineClient(handler.Client());

        var page = await client.ListSessionsAsync(limit: 10, offset: 20);
        var devices = await client.GetDevicesAsync();
        var detail = await client.GetSessionAsync("20261015_202358");
        var transcript = await client.GetTranscriptAsync("20261015_202358");
        var minutes = await client.GetMinutesAsync("20261015_202358");
        var settings = await client.GetSettingsAsync();

        Assert.Equal("/sessions?limit=10&offset=20", handler.Requests[0].Path);
        Assert.Equal(7, page.Total);
        Assert.Equal(new AudioDevice(9, "Mic", 48000, 2), devices.Inputs.Single());
        Assert.Null(devices.DefaultLoopbackId);
        Assert.Equal("C:\\rec\\20261015_202358", detail.Folder);
        Assert.True(detail.Metadata!.ContainsKey("devices"));
        Assert.Equal("Me", transcript.Segments.Single().Label);
        Assert.Equal(0.9, transcript.Segments.Single().Words.Single().Probability);
        Assert.Equal("# Ata", minutes.Markdown);
        Assert.Equal("mono", settings.GetString("MIX_MODE"));
        Assert.Equal("5.0", settings.GetString("CHUNK_SECONDS"));
        Assert.Null(settings.GetString("MIC_LABEL"));
        Assert.Null(settings.GetString("MISSING"));
        Assert.Equal(["mono", "stereo"], settings.Schema.Single().Choices);
    }

    [Fact]
    public async Task Error_envelope_becomes_an_engine_api_exception_with_the_localized_message()
    {
        var handler = FakeHttpHandler.Json("""
            {"error": {"code": "session_already_active", "message": "Já existe uma gravação."}}
            """, HttpStatusCode.Conflict);

        var error = await Assert.ThrowsAsync<EngineApiException>(
            () => new EngineClient(handler.Client()).StartSessionAsync(new StartSessionRequest()));

        Assert.Equal(HttpStatusCode.Conflict, error.Status);
        Assert.Equal("session_already_active", error.Code);
        Assert.Equal("Já existe uma gravação.", error.Message);
    }

    [Theory]
    [InlineData("<html>Bad gateway</html>")]
    [InlineData("""{"detail": "Not Found"}""")]
    public async Task Other_error_bodies_become_a_generic_http_error(string body)
    {
        var handler = FakeHttpHandler.Json(body, HttpStatusCode.BadGateway);

        var error = await Assert.ThrowsAsync<EngineApiException>(
            () => new EngineClient(handler.Client()).GetHealthAsync());

        Assert.Equal("http_error", error.Code);
        Assert.Equal("HTTP 502", error.Message);
    }

    [Fact]
    public async Task Connection_failures_become_engine_unavailable()
    {
        var handler = new FakeHttpHandler(_ => throw new HttpRequestException("refused"));

        var error = await Assert.ThrowsAsync<EngineUnavailableException>(
            () => new EngineClient(handler.Client()).GetHealthAsync());

        Assert.IsType<HttpRequestException>(error.InnerException);
    }

    [Fact]
    public async Task Ids_are_escaped_in_paths()
    {
        var handler = FakeHttpHandler.Json("""{"markdown": ""}""");

        await new EngineClient(handler.Client()).GetMinutesAsync("../etc");

        Assert.Equal("/sessions/..%2Fetc/minutes", handler.Requests.Single().Path);
    }

    [Fact]
    public async Task An_empty_body_is_an_error()
    {
        var handler = FakeHttpHandler.Json("null");

        await Assert.ThrowsAsync<System.Text.Json.JsonException>(
            () => new EngineClient(handler.Client()).GetHealthAsync());
    }

    private static HttpResponseMessage Respond(string json) =>
        new(HttpStatusCode.OK)
        {
            Content = new StringContent(json, System.Text.Encoding.UTF8, "application/json"),
        };

    [Fact]
    public async Task Settings_updates_are_put_and_report_restart_keys()
    {
        var handler = FakeHttpHandler.Json("""
            {"values": {"CHUNK_SECONDS": 8.0, "WHISPER_MODEL": "medium"}, "restart_required": ["WHISPER_MODEL"]}
            """);

        var result = await new EngineClient(handler.Client())
            .UpdateSettingsAsync(new Dictionary<string, object?> { ["CHUNK_SECONDS"] = 8, ["MIC_LABEL"] = null });

        var (method, path, body) = handler.Requests.Single();
        Assert.Equal((HttpMethod.Put, "/settings"), (method, path));
        Assert.Equal("""{"values":{"CHUNK_SECONDS":8,"MIC_LABEL":null}}""", body);
        Assert.Equal(["WHISPER_MODEL"], result.RestartRequired);
        Assert.Equal(8.0, result.Values["CHUNK_SECONDS"].GetDouble());
    }

    [Fact]
    public async Task An_invalid_setting_error_names_the_key()
    {
        var handler = FakeHttpHandler.Json("""
            {"error": {"code": "invalid_setting", "message": "Invalid value", "key": "CHUNK_SECONDS"}}
            """, (HttpStatusCode)422);

        var error = await Assert.ThrowsAsync<EngineApiException>(() => new EngineClient(handler.Client())
            .UpdateSettingsAsync(new Dictionary<string, object?> { ["CHUNK_SECONDS"] = 500 }));

        Assert.Equal(("invalid_setting", "CHUNK_SECONDS"), (error.Code, error.Key));
    }

    [Fact]
    public void Schema_entries_know_when_they_apply()
    {
        var schema = System.Text.Json.JsonSerializer.Deserialize<SettingSchema>(
            """{"key": "WHISPER_MODEL", "type": "string", "default": "large-v3-turbo", "choices": null, "secret": false, "group": "transcription", "applies": "restart"}""",
            EngineJson.Options)!;
        var old = System.Text.Json.JsonSerializer.Deserialize<SettingSchema>(
            """{"key": "MIX_MODE", "type": "choice", "default": "mono", "choices": ["mono"], "secret": false}""",
            EngineJson.Options)!;

        Assert.Equal(("transcription", true), (schema.Group, schema.NeedsRestart));
        Assert.Equal(("general", false), (old.Group, old.NeedsRestart));
    }
}
