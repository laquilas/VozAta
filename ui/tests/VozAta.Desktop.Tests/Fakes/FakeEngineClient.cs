using System.Net;
using System.Text.Json;
using VozAta.Client;

namespace VozAta.Desktop.Tests.Fakes;

/// <summary>Scriptable engine: canned answers, recorded calls, optional failures.</summary>
internal sealed class FakeEngineClient : IEngineClient
{
    public List<string> Calls { get; } = [];

    public List<StartSessionRequest> StartRequests { get; } = [];

    /// <summary>Health checks fail with "unavailable" this many times before succeeding.</summary>
    public int UnavailableHealthChecks { get; set; }

    public Exception? StartError { get; set; }

    public Exception? StopError { get; set; }

    public EngineHealth Health { get; set; } = new(
        "ok",
        "0.1.0",
        new GpuStatus(true, "RTX 3050", 6144),
        new SttStatus("faster_whisper", "large-v3", "auto"),
        new LlmStatus("ollama", "qwen2.5:7b", true));

    public Dictionary<string, object?> SettingValues { get; } = new()
    {
        ["APP_LANGUAGE"] = "en",
        ["TRANSCRIPTION_LANGUAGE"] = "pt",
    };

    public Task<EngineHealth> GetHealthAsync(CancellationToken cancellationToken = default)
    {
        Calls.Add("health");
        if (UnavailableHealthChecks > 0)
        {
            UnavailableHealthChecks--;
            throw new EngineUnavailableException("refused", new HttpRequestException("refused"));
        }

        return Task.FromResult(Health);
    }

    public Task<DeviceList> GetDevicesAsync(CancellationToken cancellationToken = default) =>
        Task.FromResult(new DeviceList([], [], null, null));

    public Task<SessionSummary> StartSessionAsync(
        StartSessionRequest request, CancellationToken cancellationToken = default)
    {
        Calls.Add("start");
        StartRequests.Add(request);
        return StartError is null ? Task.FromResult(Summary("recording")) : Task.FromException<SessionSummary>(StartError);
    }

    public Task<SessionSummary> PauseSessionAsync(CancellationToken cancellationToken = default) =>
        Task.FromResult(Summary("paused"));

    public Task<SessionSummary> ResumeSessionAsync(CancellationToken cancellationToken = default) =>
        Task.FromResult(Summary("recording"));

    public Task<SessionSummary> StopSessionAsync(CancellationToken cancellationToken = default)
    {
        Calls.Add("stop");
        return StopError is null ? Task.FromResult(Summary("finalizing")) : Task.FromException<SessionSummary>(StopError);
    }

    public Task<SessionPage> ListSessionsAsync(
        int limit = 50, int offset = 0, CancellationToken cancellationToken = default) =>
        Task.FromResult(new SessionPage([], 0));

    public Task<SessionDetail> GetSessionAsync(string id, CancellationToken cancellationToken = default) =>
        throw new NotSupportedException();

    public Task<Transcript> GetTranscriptAsync(string id, CancellationToken cancellationToken = default) =>
        throw new NotSupportedException();

    public Task<Minutes> GetMinutesAsync(string id, CancellationToken cancellationToken = default) =>
        throw new NotSupportedException();

    public Task RegenerateMinutesAsync(string id, CancellationToken cancellationToken = default) =>
        throw new NotSupportedException();

    public Task<EngineSettings> GetSettingsAsync(CancellationToken cancellationToken = default)
    {
        Calls.Add("settings");
        var values = SettingValues.ToDictionary(
            pair => pair.Key, pair => JsonSerializer.SerializeToElement(pair.Value));
        return Task.FromResult(new EngineSettings(values, []));
    }

    public static EngineApiException ApiError(string code, string message) =>
        new(HttpStatusCode.Conflict, code, message);

    private static SessionSummary Summary(string status) =>
        new("20261016_090000", status, DateTimeOffset.Now, null, 0, "pt", false);
}
