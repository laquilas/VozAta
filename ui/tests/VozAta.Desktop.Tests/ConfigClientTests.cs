using System.Net;
using VozAta.Client;
using VozAta.Desktop.Tests.Fakes;

namespace VozAta.Desktop.Tests;

public sealed class ConfigClientTests
{
    [Fact]
    public async Task Options_are_read_by_source_with_reachability()
    {
        var handler = FakeHttpHandler.Json("""
            {"options": {"whisper_models": [{"value": "large-v3", "label": "large-v3", "available": false}],
                         "ollama_models": []},
             "reachable": {"ollama_models": false}}
            """);

        var options = await new EngineClient(handler.Client()).GetSettingOptionsAsync();

        var model = Assert.Single(options.Options["whisper_models"]);
        Assert.Equal(("large-v3", "large-v3", false), (model.Value, model.Label, model.Available));
        Assert.Empty(options.Options["ollama_models"]);
        Assert.False(options.Reachable["ollama_models"]);
        Assert.Equal((HttpMethod.Get, "/settings/options"), (handler.Requests[0].Method, handler.Requests[0].Path));
    }

    [Fact]
    public async Task A_connection_test_posts_to_its_target()
    {
        var handler = FakeHttpHandler.Json("""{"ok": false, "message": "The service rejected the credentials (HTTP 401)."}""");

        var result = await new EngineClient(handler.Client()).TestConnectionAsync(ConnectionTargets.HfToken);

        Assert.False(result.Ok);
        Assert.Equal("The service rejected the credentials (HTTP 401).", result.Message);
        Assert.Equal((HttpMethod.Post, "/settings/test/hf_token"), (handler.Requests[0].Method, handler.Requests[0].Path));
        Assert.Null(handler.Requests[0].Body);
    }

    [Fact]
    public async Task Clearing_the_cache_deletes_it_and_reads_the_freed_bytes()
    {
        var handler = FakeHttpHandler.Json("""{"freed_bytes": 2048}""");

        var cleared = await new EngineClient(handler.Client()).ClearAudioCacheAsync();

        Assert.Equal(2048, cleared.FreedBytes);
        Assert.Equal((HttpMethod.Delete, "/storage/cache"), (handler.Requests[0].Method, handler.Requests[0].Path));
    }

    [Fact]
    public async Task Health_reads_the_storage_sizes()
    {
        var handler = FakeHttpHandler.Json("""
            {"engine": "ok", "version": "0.1.0",
             "gpu": {"available": false, "name": null, "vram_total_mb": null},
             "stt": {"provider": "faster_whisper", "model": "small", "device": "cpu"},
             "llm": {"provider": "ollama", "model": "qwen2.5:7b", "reachable": false},
             "storage": {"backend": "sqlite", "database": "C:\\data\\vozata.db", "warning": null,
                         "size_bytes": 4096, "audio_cache_bytes": 1024}}
            """);

        var health = await new EngineClient(handler.Client()).GetHealthAsync();

        Assert.Equal(new StorageStatus("sqlite", @"C:\data\vozata.db", null, 4096, 1024), health.Storage);
    }

    [Fact]
    public async Task The_schema_names_its_options_source()
    {
        var handler = FakeHttpHandler.Json("""
            {"values": {"WHISPER_MODEL": "small"},
             "schema": [{"key": "WHISPER_MODEL", "type": "string", "default": "large-v3-turbo", "choices": null,
                         "secret": false, "group": "transcription", "applies": "restart",
                         "options_source": "whisper_models"}]}
            """);

        var settings = await new EngineClient(handler.Client()).GetSettingsAsync();

        Assert.Equal("whisper_models", Assert.Single(settings.Schema).OptionsSource);
    }

    [Fact]
    public async Task An_engine_error_on_a_test_is_an_api_exception()
    {
        var handler = FakeHttpHandler.Json(
            """{"error": {"code": "invalid_request", "message": "bad target"}}""", HttpStatusCode.UnprocessableEntity);

        var error = await Assert.ThrowsAsync<EngineApiException>(
            () => new EngineClient(handler.Client()).TestConnectionAsync("smtp"));

        Assert.Equal("invalid_request", error.Code);
    }
}
