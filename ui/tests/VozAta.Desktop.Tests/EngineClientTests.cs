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
        Assert.Equal("""{"mic_device_id":9,"system_device_id":null,"language":"pt","template":null}""", body);
        Assert.Equal("20261015_202358", summary.Id);
        Assert.Equal(new DateTimeOffset(2026, 10, 15, 20, 23, 58, TimeSpan.FromHours(-3)), summary.StartedAt);
        Assert.Null(summary.EndedAt);
        Assert.Equal(1.5, summary.DurationSeconds);
    }

    [Fact]
    public async Task Start_and_regenerate_send_the_chosen_template()
    {
        var handler = FakeHttpHandler.Json(Summary, HttpStatusCode.Created);
        var client = new EngineClient(handler.Client());

        await client.StartSessionAsync(new StartSessionRequest(Language: "en", Template: "daily"));
        await client.RegenerateMinutesAsync("20261015_202358", "client");
        await client.RegenerateMinutesAsync("20261015_202358");

        Assert.Equal(
            [
                """{"mic_device_id":null,"system_device_id":null,"language":"en","template":"daily"}""",
                """{"template":"client"}""",
                """{"template":null}""",
            ],
            handler.Requests.Select(request => request.Body));
    }

    [Fact]
    public async Task Start_sends_the_meeting_terms_only_when_given()
    {
        var handler = FakeHttpHandler.Json(Summary, HttpStatusCode.Created);
        var client = new EngineClient(handler.Client());

        await client.StartSessionAsync(new StartSessionRequest(Language: "en", Vocabulary: ["Jessica", "N5"]));

        Assert.Equal(
            """{"mic_device_id":null,"system_device_id":null,"language":"en","template":null,"vocabulary":["Jessica","N5"]}""",
            handler.Requests.Single().Body);
    }

    [Fact]
    public async Task Start_sends_the_title_only_when_set_and_reads_it_back()
    {
        var handler = FakeHttpHandler.Json(
            """{"id": "20261015_202358", "status": "recording", "started_at": null, "ended_at": null, "duration_seconds": 0, "language": "en", "has_minutes": false, "title": "Weekly sync"}""",
            HttpStatusCode.Created);
        var client = new EngineClient(handler.Client());

        var summary = await client.StartSessionAsync(new StartSessionRequest(Language: "en", Title: "Weekly sync"));
        await client.StartSessionAsync(new StartSessionRequest(Language: "en"));

        Assert.Equal(
            [
                """{"mic_device_id":null,"system_device_id":null,"language":"en","template":null,"title":"Weekly sync"}""",
                """{"mic_device_id":null,"system_device_id":null,"language":"en","template":null}""",
            ],
            handler.Requests.Select(request => request.Body));
        Assert.Equal("Weekly sync", summary.Title);
    }

    [Fact]
    public async Task A_summary_without_a_title_is_untitled()
    {
        var handler = FakeHttpHandler.Json(Summary, HttpStatusCode.Created);

        var summary = await new EngineClient(handler.Client()).StartSessionAsync(new StartSessionRequest());

        Assert.Null(summary.Title);
    }

    [Fact]
    public async Task The_title_is_patched_and_null_clears_it()
    {
        var handler = FakeHttpHandler.Json(
            """{"id": "20261015_202358", "status": "done", "started_at": null, "ended_at": null, "duration_seconds": 3, "language": "en", "has_minutes": true, "title": null}""");
        var client = new EngineClient(handler.Client());

        await client.UpdateSessionTitleAsync("20261015_202358", "Retro");
        var summary = await client.UpdateSessionTitleAsync("20261015_202358", null);

        Assert.Equal(
            [
                (HttpMethod.Patch, "/sessions/20261015_202358", (string?)"""{"title":"Retro"}"""),
                (HttpMethod.Patch, "/sessions/20261015_202358", (string?)"""{"title":null}"""),
            ],
            handler.Requests);
        Assert.Null(summary.Title);
    }

    [Fact]
    public async Task Meetings_of_a_week_are_read_by_day_with_the_new_summary_fields()
    {
        var handler = FakeHttpHandler.Json("""
            {"days": [{"date": "2026-10-14", "total_seconds": 4200.5, "items": [
               {"id": "20261014_153000", "status": "done", "started_at": "2026-10-14T15:30:00-03:00",
                "ended_at": "2026-10-14T15:40:00-03:00", "duration_seconds": 600.5, "language": "en",
                "has_minutes": true, "title": "Weekly sync", "speaker_count": 3,
                "has_action_items": true, "template": "daily"}]}],
             "total_seconds": 4200.5, "has_earlier": true, "storage": "sqlite"}
            """);

        var week = await new EngineClient(handler.Client()).ListSessionDaysAsync(
            new DateOnly(2026, 10, 12), new DateOnly(2026, 10, 18));

        Assert.Equal("/sessions?from=2026-10-12&to=2026-10-18", handler.Requests.Single().Path);
        var day = week.Days.Single();
        Assert.Equal(new DateOnly(2026, 10, 14), day.Date);
        Assert.Equal(4200.5, day.TotalSeconds);
        var item = day.Items.Single();
        Assert.Equal((3, true, "daily"), (item.SpeakerCount, item.HasActionItems, item.Template));
        Assert.True(week.HasEarlier);
        Assert.False(week.DeletesToRecycleBin);
        Assert.Equal(4200.5, week.TotalSeconds);
    }

    [Fact]
    public async Task Summary_deserializes_processing_or_null()
    {
        var handler = FakeHttpHandler.Json("""
            {"items": [
              {"id": "a", "status": "done", "started_at": null, "ended_at": null, "duration_seconds": 1,
               "language": "en", "has_minutes": false,
               "processing": {"state": "running", "percent": 55, "step": "minutes"}},
              {"id": "b", "status": "done", "started_at": null, "ended_at": null, "duration_seconds": 1,
               "language": "en", "has_minutes": false, "processing": null},
              {"id": "c", "status": "done", "started_at": null, "ended_at": null, "duration_seconds": 1,
               "language": "en", "has_minutes": false,
               "processing": {"state": "queued", "percent": 0, "step": null, "position": 1}}],
             "total": 3}
            """);

        var page = await new EngineClient(handler.Client()).ListSessionsAsync();

        Assert.Equal(new ProcessingInfo("running", 55, "minutes", null), page.Items[0].Processing);
        Assert.Null(page.Items[1].Processing);
        Assert.Equal(new ProcessingInfo("queued", 0, null, 1), page.Items[2].Processing);
    }

    [Fact]
    public async Task A_summary_without_the_phase_36_fields_has_defaults()
    {
        var handler = FakeHttpHandler.Json(Summary, HttpStatusCode.Created);

        var summary = await new EngineClient(handler.Client()).StartSessionAsync(new StartSessionRequest());

        Assert.Equal((0, false, null), (summary.SpeakerCount, summary.HasActionItems, summary.Template));
        Assert.True(new SessionDays([], 0, false).DeletesToRecycleBin);
    }

    [Fact]
    public async Task Delete_sends_a_delete_and_a_409_becomes_an_api_exception()
    {
        var calls = 0;
        var handler = new FakeHttpHandler(_ => ++calls == 1
            ? new HttpResponseMessage(HttpStatusCode.NoContent)
            : new HttpResponseMessage(HttpStatusCode.Conflict)
            {
                Content = new StringContent(
                    """{"error": {"code": "session_still_active", "message": "Still recording."}}""",
                    System.Text.Encoding.UTF8,
                    "application/json"),
            });
        var client = new EngineClient(handler.Client());

        await client.DeleteSessionAsync("20261015_202358");
        var error = await Assert.ThrowsAsync<EngineApiException>(() => client.DeleteSessionAsync("20261015_202358"));

        Assert.Equal((HttpMethod.Delete, "/sessions/20261015_202358", (string?)null), handler.Requests[0]);
        Assert.Equal("session_still_active", error.Code);
        Assert.Equal("Still recording.", error.Message);
    }

    [Fact]
    public async Task Start_sends_the_translation_language_only_when_chosen()
    {
        var handler = FakeHttpHandler.Json(Summary, HttpStatusCode.Created);
        var client = new EngineClient(handler.Client());

        await client.StartSessionAsync(new StartSessionRequest(Language: "en", TranslateTo: "pt"));

        Assert.Equal(
            """{"mic_device_id":null,"system_device_id":null,"language":"en","template":null,"translate_to":"pt"}""",
            handler.Requests.Single().Body);
    }

    [Fact]
    public async Task StartSessionRequest_serializes_live_transcription()
    {
        var handler = FakeHttpHandler.Json(Summary, HttpStatusCode.Created);
        var client = new EngineClient(handler.Client());

        await client.StartSessionAsync(new StartSessionRequest(Language: "en", LiveTranscription: false));
        await client.StartSessionAsync(new StartSessionRequest(Language: "en"));

        Assert.Contains("\"live_transcription\":false", handler.Requests[0].Body);
        Assert.DoesNotContain("live_transcription", handler.Requests[1].Body);
    }

    [Fact]
    public async Task Vocabulary_is_read_and_replaced()
    {
        var handler = FakeHttpHandler.Json("""{"terms": ["Avalonia", "Jéssica"]}""");
        var client = new EngineClient(handler.Client());

        var read = await client.GetVocabularyAsync();
        var saved = await client.UpdateVocabularyAsync([" Avalonia ", "Jessica"]);

        Assert.Equal(["Avalonia", "Jéssica"], read);
        Assert.Equal(["Avalonia", "Jéssica"], saved);
        Assert.Equal((HttpMethod.Get, "/vocabulary", (string?)null), handler.Requests[0]);
        Assert.Equal(HttpMethod.Put, handler.Requests[1].Method);
        Assert.Equal("/vocabulary", handler.Requests[1].Path);
        Assert.Equal("""{"terms":[" Avalonia ","Jessica"]}""", handler.Requests[1].Body);
    }

    [Fact]
    public async Task Transcript_edits_are_put_in_snake_case_and_reverted_with_delete()
    {
        var handler = FakeHttpHandler.Json("""{"source": "edited"}""");
        var client = new EngineClient(handler.Client());

        var result = await client.UpdateTranscriptAsync("20261015_202358", [new SegmentTextEdit("mic-000001", "Hello world.")]);
        await client.RevertTranscriptAsync("20261015_202358");

        Assert.Equal("edited", result.Source);
        Assert.Equal(
            [
                (HttpMethod.Put, "/sessions/20261015_202358/transcript",
                 (string?)"""{"segments":[{"segment_id":"mic-000001","text":"Hello world."}]}"""),
                (HttpMethod.Delete, "/sessions/20261015_202358/transcript/edits", null),
            ],
            handler.Requests);
    }

    [Fact]
    public async Task Speakers_are_read_and_names_are_sent_per_id()
    {
        const string Speakers = """
            {"speakers": {"mic": {"name": null, "default_label": "Me"},
                          "system:1": {"name": "Alice", "default_label": "User 1"}}}
            """;
        var handler = FakeHttpHandler.Json(Speakers);
        var client = new EngineClient(handler.Client());

        var read = await client.GetSpeakersAsync("20261015_202358");
        var saved = await client.UpdateSpeakersAsync(
            "20261015_202358", new Dictionary<string, string?> { ["system:1"] = "Alice", ["mic"] = null });

        Assert.Equal(["mic", "system:1"], read.Speakers.Keys);
        Assert.Equal(new SpeakerInfo(null, "Me"), read.Speakers["mic"]);
        Assert.Equal(new SpeakerInfo("Alice", "User 1"), saved.Speakers["system:1"]);
        Assert.Equal(
            [
                (HttpMethod.Get, "/sessions/20261015_202358/speakers", (string?)null),
                (HttpMethod.Put, "/sessions/20261015_202358/speakers",
                 """{"speakers":{"system:1":{"name":"Alice"},"mic":{"name":null}}}"""),
            ],
            handler.Requests);
    }

    [Fact]
    public async Task A_rejected_transcript_edit_throws_the_engine_error()
    {
        var handler = FakeHttpHandler.Json(
            """{"error": {"code": "empty_segment_text", "message": "Segment cannot be empty."}}""",
            System.Net.HttpStatusCode.UnprocessableEntity);

        var error = await Assert.ThrowsAsync<EngineApiException>(
            () => new EngineClient(handler.Client()).UpdateTranscriptAsync("20261015_202358", [new SegmentTextEdit("mic-000001", " ")]));

        Assert.Equal("empty_segment_text", error.Code);
    }

    [Fact]
    public async Task Templates_are_read_in_order()
    {
        var handler = FakeHttpHandler.Json("""
            [{"id": "general", "name": "General meeting"}, {"id": "one_on_one", "name": "One-on-one"}]
            """);

        var templates = await new EngineClient(handler.Client()).GetTemplatesAsync();

        Assert.Equal([new MinutesTemplate("general", "General meeting"), new MinutesTemplate("one_on_one", "One-on-one")], templates);
        Assert.Equal("One-on-one", templates[1].ToString());
        Assert.Equal((HttpMethod.Get, "/templates", (string?)null), handler.Requests.Single());
    }

    [Fact]
    public async Task Search_escapes_the_query_and_reads_the_hits()
    {
        var handler = FakeHttpHandler.Json("""
            {"hits": [{"session_id": "20261015_202358", "segment_id": "mic-000001", "start": 83.12,
                       "speaker_id": "mic", "label": "Me", "snippet": "a \u0002decisão\u0003 final"}]}
            """);

        var results = await new EngineClient(handler.Client()).SearchAsync("decisão & \"OR\"", limit: 20);

        Assert.Equal(
            (HttpMethod.Get, "/search?q=decis%C3%A3o%20%26%20%22OR%22&limit=20", (string?)null),
            handler.Requests.Single());
        Assert.Equal(
            new SearchHit("20261015_202358", "mic-000001", 83.12, "mic", "Me", "a \u0002decisão\u0003 final"),
            results.Hits.Single());
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
        await client.RecoverSessionAsync("20261014_090000");

        Assert.Equal(
            ["/sessions/current/pause", "/sessions/current/resume", "/sessions/current/stop",
             "/sessions/20261015_202358/minutes", "/sessions/20261014_090000/recover"],
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
                 "edited": false, "words": [{"text": "Oi.", "start": 1.0, "end": 2.0, "probability": 0.9}],
                 "translation": {"language": "en", "text": "Hi."}}]}
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
        Assert.Equal(new SegmentTranslation("en", "Hi."), transcript.Segments.Single().Translation);
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

    [Fact]
    public async Task Exports_download_bytes_with_the_engine_file_name()
    {
        var handler = new FakeHttpHandler(_ =>
        {
            var content = new ByteArrayContent([0x25, 0x50, 0x44, 0x46]);
            content.Headers.ContentDisposition = new System.Net.Http.Headers.ContentDispositionHeaderValue("attachment")
            {
                FileName = "\"20261015_202358-minutes.pdf\"",
            };
            return new HttpResponseMessage(HttpStatusCode.OK) { Content = content };
        });

        var file = await new EngineClient(handler.Client()).ExportSessionAsync("20261015_202358", "pdf");

        Assert.Equal("/sessions/20261015_202358/export?format=pdf", handler.Requests.Single().Path);
        Assert.Equal("20261015_202358-minutes.pdf", file.FileName);
        Assert.Equal([0x25, 0x50, 0x44, 0x46], file.Content);
    }

    [Fact]
    public async Task Audio_is_streamed_into_the_destination()
    {
        var handler = new FakeHttpHandler(_ => new HttpResponseMessage(HttpStatusCode.OK) { Content = new ByteArrayContent([0x52, 0x49, 0x46, 0x46]) });
        using var destination = new MemoryStream();

        await new EngineClient(handler.Client()).DownloadAudioAsync("20261015_202358", "mixed", destination);

        Assert.Equal("/sessions/20261015_202358/audio/mixed", handler.Requests.Single().Path);
        Assert.Equal([0x52, 0x49, 0x46, 0x46], destination.ToArray());
    }

    [Fact]
    public async Task Deleting_the_audio_sends_a_delete_to_the_audio_path()
    {
        var handler = new FakeHttpHandler(_ => new HttpResponseMessage(HttpStatusCode.NoContent));

        await new EngineClient(handler.Client()).DeleteSessionAudioAsync("20261015_202358");

        Assert.Equal((HttpMethod.Delete, "/sessions/20261015_202358/audio"), (handler.Requests.Single().Method, handler.Requests.Single().Path));
    }

    [Fact]
    public async Task The_bundle_is_streamed_into_the_destination()
    {
        var handler = new FakeHttpHandler(_ => new HttpResponseMessage(HttpStatusCode.OK) { Content = new ByteArrayContent([0x50, 0x4B]) });
        using var destination = new MemoryStream();

        await new EngineClient(handler.Client()).DownloadBundleAsync("20261015_202358", destination);

        Assert.Equal("/sessions/20261015_202358/bundle", handler.Requests.Single().Path);
        Assert.Equal([0x50, 0x4B], destination.ToArray());
    }

    [Fact]
    public async Task A_bundle_is_posted_as_a_zip_body_and_the_result_read()
    {
        string? contentType = null;
        var handler = new FakeHttpHandler(request =>
        {
            contentType = request.Content?.Headers.ContentType?.MediaType;
            return new HttpResponseMessage(HttpStatusCode.OK)
            {
                Content = new StringContent("""{"id": "20261015_202358", "mode": "audio_restored"}""", System.Text.Encoding.UTF8, "application/json"),
            };
        });
        using var bundle = new MemoryStream("PK"u8.ToArray());

        var result = await new EngineClient(handler.Client()).ImportBundleAsync(bundle);

        Assert.Equal((HttpMethod.Post, "/sessions/import", "PK"), handler.Requests.Single());
        Assert.Equal("application/zip", contentType);
        Assert.Equal(new ImportedSession("20261015_202358", "audio_restored"), result);
        Assert.True(result.AudioRestored);
        Assert.False(new ImportedSession("x", "imported").AudioRestored);
    }

    [Fact]
    public async Task A_refused_bundle_raises_the_engine_error()
    {
        var handler = new FakeHttpHandler(_ => new HttpResponseMessage(HttpStatusCode.Conflict)
        {
            Content = new StringContent("{\"error\":{\"code\":\"session_exists\",\"message\":\"Already there.\"}}"),
        });
        using var bundle = new MemoryStream("PK"u8.ToArray());

        var error = await Assert.ThrowsAsync<EngineApiException>(
            () => new EngineClient(handler.Client()).ImportBundleAsync(bundle));

        Assert.Equal(("session_exists", "Already there."), (error.Code, error.Message));
    }

    [Fact]
    public async Task Missing_audio_raises_the_engine_error()
    {
        var handler = new FakeHttpHandler(_ => new HttpResponseMessage(HttpStatusCode.NotFound)
        {
            Content = new StringContent("{\"error\":{\"code\":\"audio_not_found\",\"message\":\"No audio.\"}}"),
        });

        var error = await Assert.ThrowsAsync<EngineApiException>(
            () => new EngineClient(handler.Client()).DownloadAudioAsync("s1", "mic", Stream.Null));

        Assert.Equal("audio_not_found", error.Code);
    }

    [Fact]
    public async Task An_export_without_a_file_name_gets_a_default_one()
    {
        var handler = new FakeHttpHandler(_ => new HttpResponseMessage(HttpStatusCode.OK) { Content = new ByteArrayContent([1]) });

        var file = await new EngineClient(handler.Client()).ExportSessionAsync("s1", "md");

        Assert.Equal("s1-minutes.md", file.FileName);
    }
}
