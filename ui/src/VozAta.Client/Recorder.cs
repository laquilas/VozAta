using System.Diagnostics.CodeAnalysis;
using System.Net.Http.Json;
using System.Runtime.CompilerServices;
using System.Text.Json;

namespace VozAta.Client;

/// <summary>A recording of the recorder process (phase 61): <c>RecordingSummary</c> of its API.</summary>
public sealed record RecordingSummary(
    string? Id,
    string Status,
    string? StartedAt = null,
    double DurationSeconds = 0,
    IReadOnlyDictionary<string, JsonElement>? Options = null)
{
    public bool IsActive => Status is "recording" or "paused";
}

/// <summary><c>GET /health</c> of the recorder.</summary>
public sealed record RecorderHealth(string Recorder, string Version, RecordingSummary? Recording);

/// <summary>
/// <c>POST /recordings</c>: the devices and the meeting options (language, template, vocabulary,
/// translate_to, title, live_transcription), which the engine applies when it attaches.
/// </summary>
public sealed record StartRecordingRequest(
    int? MicDeviceId,
    int? SystemDeviceId,
    IReadOnlyDictionary<string, object?> Options);

/// <summary>
/// The recorder process API (phase 61): it records from the first second, with or without the
/// engine. Errors use the engine's exceptions (<see cref="EngineApiException"/>,
/// <see cref="EngineUnavailableException"/>), so callers handle both the same way.
/// </summary>
public interface IRecorderClient
{
    Task<RecorderHealth> GetHealthAsync(CancellationToken cancellationToken = default);

    Task<DeviceList> GetDevicesAsync(CancellationToken cancellationToken = default);

    Task<RecordingSummary> StartAsync(StartRecordingRequest request, CancellationToken cancellationToken = default);

    Task<RecordingSummary> PauseAsync(CancellationToken cancellationToken = default);

    Task<RecordingSummary> ResumeAsync(CancellationToken cancellationToken = default);

    Task<RecordingSummary> StopAsync(CancellationToken cancellationToken = default);

    /// <summary><c>PATCH /recordings/current</c>: merge options (e.g. the title) into the recording.</summary>
    Task<RecordingSummary> UpdateOptionsAsync(
        IReadOnlyDictionary<string, object?> options, CancellationToken cancellationToken = default);
}

public sealed class RecorderClient(HttpClient http) : IRecorderClient
{
    public Task<RecorderHealth> GetHealthAsync(CancellationToken cancellationToken = default) =>
        SendAsync<RecorderHealth>(HttpMethod.Get, "health", null, cancellationToken);

    public Task<DeviceList> GetDevicesAsync(CancellationToken cancellationToken = default) =>
        SendAsync<DeviceList>(HttpMethod.Get, "devices", null, cancellationToken);

    public Task<RecordingSummary> StartAsync(StartRecordingRequest request, CancellationToken cancellationToken = default) =>
        SendAsync<RecordingSummary>(HttpMethod.Post, "recordings", request, cancellationToken);

    public Task<RecordingSummary> PauseAsync(CancellationToken cancellationToken = default) =>
        SendAsync<RecordingSummary>(HttpMethod.Post, "recordings/current/pause", null, cancellationToken);

    public Task<RecordingSummary> ResumeAsync(CancellationToken cancellationToken = default) =>
        SendAsync<RecordingSummary>(HttpMethod.Post, "recordings/current/resume", null, cancellationToken);

    public Task<RecordingSummary> StopAsync(CancellationToken cancellationToken = default) =>
        SendAsync<RecordingSummary>(HttpMethod.Post, "recordings/current/stop", null, cancellationToken);

    public Task<RecordingSummary> UpdateOptionsAsync(
        IReadOnlyDictionary<string, object?> options, CancellationToken cancellationToken = default) =>
        SendAsync<RecordingSummary>(HttpMethod.Patch, "recordings/current", new { options }, cancellationToken);

    private async Task<T> SendAsync<T>(HttpMethod method, string path, object? body, CancellationToken cancellationToken)
    {
        using var request = new HttpRequestMessage(method, path);
        if (body is not null)
        {
            request.Content = JsonContent.Create(body, options: EngineJson.Options);
        }

        HttpResponseMessage response;
        try
        {
            response = await http.SendAsync(request, cancellationToken);
        }
        catch (HttpRequestException error)
        {
            throw new EngineUnavailableException(error.Message, error);
        }

        using (response)
        {
            if (!response.IsSuccessStatusCode)
            {
                throw await ToExceptionAsync(response, cancellationToken);
            }

            return await response.Content.ReadFromJsonAsync<T>(EngineJson.Options, cancellationToken)
                ?? throw new JsonException($"Empty response from {path}");
        }
    }

    private static async Task<Exception> ToExceptionAsync(HttpResponseMessage response, CancellationToken cancellationToken)
    {
        var text = await response.Content.ReadAsStringAsync(cancellationToken);
        try
        {
            if (JsonSerializer.Deserialize<ErrorEnvelope>(text, EngineJson.Options)?.Error is { } error)
            {
                return new EngineApiException(response.StatusCode, error.Code, error.Message);
            }
        }
        catch (JsonException)
        {
            // not the envelope: a generic error below
        }

        return new EngineApiException(response.StatusCode, "http_error", $"HTTP {(int)response.StatusCode}");
    }

    private sealed record ErrorEnvelope(ErrorBody? Error);

    private sealed record ErrorBody(string Code, string Message);
}

/// <summary>Events of the recorder's <c>/events</c> stream (Server-Sent Events).</summary>
public abstract record RecorderEvent;

/// <summary>The current recording: on every change and every second while recording; id null when idle.</summary>
public sealed record RecorderStatusEvent(RecordingSummary Recording) : RecorderEvent;

public sealed record RecorderLevelEvent(string Channel, double RmsDb) : RecorderEvent;

/// <summary>A problem the recording survives (<c>write_failed</c>, <c>disk_backlog</c>, <c>manifest_write_failed</c>).</summary>
public sealed record RecorderErrorEvent(string Code, string Message) : RecorderEvent;

/// <summary>Raised by the client: the stream to the recorder opened or dropped.</summary>
public sealed record RecorderConnectionChangedEvent(bool Connected) : RecorderEvent;

public static class RecorderEventParser
{
    /// <summary>The event of one SSE message, or null for an unknown or broken one.</summary>
    public static RecorderEvent? Parse(string name, string data)
    {
        try
        {
            return name switch
            {
                "status" => JsonSerializer.Deserialize<RecordingSummary>(data, EngineJson.Options) is { } summary
                    ? new RecorderStatusEvent(summary)
                    : null,
                "level" => JsonSerializer.Deserialize<LevelData>(data, EngineJson.Options) is { } level
                    ? new RecorderLevelEvent(level.Channel, level.RmsDb)
                    : null,
                "error" => JsonSerializer.Deserialize<ErrorData>(data, EngineJson.Options) is { } error
                    ? new RecorderErrorEvent(error.Code, error.Message)
                    : null,
                _ => null,
            };
        }
        catch (JsonException)
        {
            return null;
        }
    }

    private sealed record LevelData(string Channel, double RmsDb);

    private sealed record ErrorData(string Code, string Message);
}

/// <summary>Opens the recorder's event stream as text lines.</summary>
public interface IEventStreamSource
{
    Task<TextReader> OpenAsync(CancellationToken cancellationToken);
}

/// <summary>The recorder event stream.</summary>
public interface IRecorderEvents
{
    /// <summary>Events until cancelled; reconnects by itself and reports it with <see cref="RecorderConnectionChangedEvent"/>.</summary>
    IAsyncEnumerable<RecorderEvent> ReadAllAsync(CancellationToken cancellationToken = default);
}

/// <summary>Reads the SSE stream; reconnects with the same backoff as <see cref="EngineEvents"/>.</summary>
public sealed class RecorderEvents(
    IEventStreamSource source,
    Func<TimeSpan, CancellationToken, Task>? delay = null) : IRecorderEvents
{
    private readonly Func<TimeSpan, CancellationToken, Task> _delay = delay ?? Task.Delay;

    public async IAsyncEnumerable<RecorderEvent> ReadAllAsync(
        [EnumeratorCancellation] CancellationToken cancellationToken = default)
    {
        var retry = EngineEvents.FirstRetry;
        bool? connected = null; // reported on every change, the first failure too
        while (!cancellationToken.IsCancellationRequested)
        {
            var reader = await TryOpenAsync(cancellationToken);
            if (reader is not null)
            {
                retry = EngineEvents.FirstRetry;
                using (reader)
                {
                    connected = true;
                    yield return new RecorderConnectionChangedEvent(true);
                    string? name = null;
                    while (await TryReadLineAsync(reader, cancellationToken) is { } line)
                    {
                        if (line.StartsWith("event: ", StringComparison.Ordinal))
                        {
                            name = line[7..];
                        }
                        else if (line.StartsWith("data: ", StringComparison.Ordinal) && name is not null)
                        {
                            if (RecorderEventParser.Parse(name, line[6..]) is { } recorderEvent)
                            {
                                yield return recorderEvent;
                            }

                            name = null;
                        }
                    }
                }

                if (cancellationToken.IsCancellationRequested)
                {
                    yield break;
                }
            }

            if (connected != false)
            {
                connected = false;
                yield return new RecorderConnectionChangedEvent(false);
            }

            if (!await TryDelayAsync(retry, cancellationToken))
            {
                yield break;
            }

            retry = TimeSpan.FromTicks(Math.Min(retry.Ticks * 2, EngineEvents.MaxRetry.Ticks));
        }
    }

    private async Task<TextReader?> TryOpenAsync(CancellationToken cancellationToken)
    {
        try
        {
            return await source.OpenAsync(cancellationToken);
        }
        catch (Exception error) when (error is HttpRequestException or IOException or OperationCanceledException)
        {
            return null;
        }
    }

    private static async Task<string?> TryReadLineAsync(TextReader reader, CancellationToken cancellationToken)
    {
        try
        {
            return await reader.ReadLineAsync(cancellationToken);
        }
        catch (Exception error) when (error is IOException or HttpRequestException or OperationCanceledException)
        {
            return null;
        }
    }

    private async Task<bool> TryDelayAsync(TimeSpan wait, CancellationToken cancellationToken)
    {
        try
        {
            await _delay(wait, cancellationToken);
            return !cancellationToken.IsCancellationRequested;
        }
        catch (OperationCanceledException)
        {
            return false;
        }
    }
}

/// <summary>The real stream: <c>GET /events</c> read as it arrives.</summary>
[ExcludeFromCodeCoverage(Justification = "Thin wrapper over the network; covered by the manual check.")]
public sealed class HttpEventStreamSource(HttpClient http) : IEventStreamSource
{
    public async Task<TextReader> OpenAsync(CancellationToken cancellationToken)
    {
        var response = await http.GetAsync("events", HttpCompletionOption.ResponseHeadersRead, cancellationToken);
        response.EnsureSuccessStatusCode();
        var stream = await response.Content.ReadAsStreamAsync(cancellationToken);
        return new StreamReader(stream);
    }
}
