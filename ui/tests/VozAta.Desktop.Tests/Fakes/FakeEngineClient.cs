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

    public DeviceList Devices { get; set; } = new([], [], null, null);

    public Exception? DevicesError { get; set; }

    public Task<DeviceList> GetDevicesAsync(CancellationToken cancellationToken = default)
    {
        Calls.Add("devices");
        return DevicesError is null ? Task.FromResult(Devices) : Task.FromException<DeviceList>(DevicesError);
    }

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

    /// <summary>Every session, newest first (paged by <see cref="ListSessionsAsync"/>).</summary>
    public List<SessionSummary> Sessions { get; } = [];

    public Dictionary<string, SessionDetail> Details { get; } = [];

    public Dictionary<string, Transcript> Transcripts { get; } = [];

    /// <summary>Minutes per session; a missing entry answers 404 <c>minutes_not_found</c>.</summary>
    public Dictionary<string, string> MinutesText { get; } = [];

    public List<(int Limit, int Offset)> ListRequests { get; } = [];

    public List<string> Regenerated { get; } = [];

    public Exception? ListError { get; set; }

    public Exception? DetailError { get; set; }

    public Exception? RegenerateError { get; set; }

    public Task<SessionPage> ListSessionsAsync(
        int limit = 50, int offset = 0, CancellationToken cancellationToken = default)
    {
        ListRequests.Add((limit, offset));
        return ListError is null
            ? Task.FromResult(new SessionPage([.. Sessions.Skip(offset).Take(limit)], Sessions.Count))
            : Task.FromException<SessionPage>(ListError);
    }

    public Task<SessionDetail> GetSessionAsync(string id, CancellationToken cancellationToken = default) =>
        DetailError is null ? Task.FromResult(Details[id]) : Task.FromException<SessionDetail>(DetailError);

    public Task<Transcript> GetTranscriptAsync(string id, CancellationToken cancellationToken = default) =>
        Task.FromResult(Transcripts.GetValueOrDefault(id) ?? new Transcript("raw", []));

    public Task<Minutes> GetMinutesAsync(string id, CancellationToken cancellationToken = default) =>
        MinutesText.TryGetValue(id, out var markdown)
            ? Task.FromResult(new Minutes(markdown))
            : Task.FromException<Minutes>(new EngineApiException(HttpStatusCode.NotFound, "minutes_not_found", "No minutes yet."));

    public List<(string Id, string Format)> Exports { get; } = [];

    public Exception? ExportError { get; set; }

    public Task<ExportedFile> ExportSessionAsync(string id, string format, CancellationToken cancellationToken = default)
    {
        Exports.Add((id, format));
        return ExportError is null
            ? Task.FromResult(new ExportedFile($"{id}-minutes.{format}", [1, 2, 3]))
            : Task.FromException<ExportedFile>(ExportError);
    }

    public Task RegenerateMinutesAsync(string id, CancellationToken cancellationToken = default)
    {
        Regenerated.Add(id);
        return RegenerateError is null ? Task.CompletedTask : Task.FromException(RegenerateError);
    }

    public Exception? SettingsError { get; set; }

    public Task<EngineSettings> GetSettingsAsync(CancellationToken cancellationToken = default)
    {
        Calls.Add("settings");
        if (SettingsError is not null)
        {
            return Task.FromException<EngineSettings>(SettingsError);
        }

        var values = SettingValues.ToDictionary(
            pair => pair.Key, pair => JsonSerializer.SerializeToElement(pair.Value));
        return Task.FromResult(new EngineSettings(values, Schema));
    }

    public List<IReadOnlyDictionary<string, object?>> Updates { get; } = [];

    public List<SettingSchema> Schema { get; } = [];

    /// <summary>Keys the next update reports as needing a restart.</summary>
    public List<string> RestartKeys { get; } = [];

    public Exception? UpdateError { get; set; }

    public Task<SettingsUpdateResult> UpdateSettingsAsync(
        IReadOnlyDictionary<string, object?> values, CancellationToken cancellationToken = default)
    {
        Calls.Add("update-settings");
        Updates.Add(values);
        if (UpdateError is not null)
        {
            return Task.FromException<SettingsUpdateResult>(UpdateError);
        }

        foreach (var (key, value) in values)
        {
            SettingValues[key] = value;
        }

        var saved = SettingValues.ToDictionary(pair => pair.Key, pair => JsonSerializer.SerializeToElement(pair.Value));
        return Task.FromResult(new SettingsUpdateResult(saved, [.. RestartKeys.Where(values.ContainsKey)]));
    }

    public static EngineApiException ApiError(string code, string message) =>
        new(HttpStatusCode.Conflict, code, message);

    private static SessionSummary Summary(string status) =>
        new("20261016_090000", status, DateTimeOffset.Now, null, 0, "pt", false);
}
