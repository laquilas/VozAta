using System.Net;
using System.Net.Http.Json;
using System.Text.Json;

namespace VozAta.Client;

/// <summary>The engine HTTP API (docs/roadmap/api-contract.md, rows tagged 06).</summary>
public interface IEngineClient
{
    Task<EngineHealth> GetHealthAsync(CancellationToken cancellationToken = default);

    Task<DeviceList> GetDevicesAsync(CancellationToken cancellationToken = default);

    Task<SessionSummary> StartSessionAsync(
        StartSessionRequest request, CancellationToken cancellationToken = default);

    Task<SessionSummary> PauseSessionAsync(CancellationToken cancellationToken = default);

    Task<SessionSummary> ResumeSessionAsync(CancellationToken cancellationToken = default);

    Task<SessionSummary> StopSessionAsync(CancellationToken cancellationToken = default);

    Task<SessionPage> ListSessionsAsync(
        int limit = 50, int offset = 0, CancellationToken cancellationToken = default);

    Task<SessionDetail> GetSessionAsync(string id, CancellationToken cancellationToken = default);

    Task<Transcript> GetTranscriptAsync(string id, CancellationToken cancellationToken = default);

    Task<Minutes> GetMinutesAsync(string id, CancellationToken cancellationToken = default);

    Task RegenerateMinutesAsync(string id, CancellationToken cancellationToken = default);

    Task<EngineSettings> GetSettingsAsync(CancellationToken cancellationToken = default);
}

/// <summary>The engine answered with the error envelope; <see cref="Exception.Message"/> is localized.</summary>
public sealed class EngineApiException(HttpStatusCode status, string code, string message)
    : Exception(message)
{
    public HttpStatusCode Status { get; } = status;

    public string Code { get; } = code;
}

/// <summary>The engine could not be reached (not running, starting, or crashed).</summary>
public sealed class EngineUnavailableException(string message, Exception innerException)
    : Exception(message, innerException);

public sealed class EngineClient(HttpClient http) : IEngineClient
{
    public Task<EngineHealth> GetHealthAsync(CancellationToken cancellationToken = default) =>
        SendAsync<EngineHealth>(HttpMethod.Get, "health", null, cancellationToken);

    public Task<DeviceList> GetDevicesAsync(CancellationToken cancellationToken = default) =>
        SendAsync<DeviceList>(HttpMethod.Get, "devices", null, cancellationToken);

    public Task<SessionSummary> StartSessionAsync(
        StartSessionRequest request, CancellationToken cancellationToken = default) =>
        SendAsync<SessionSummary>(HttpMethod.Post, "sessions", request, cancellationToken);

    public Task<SessionSummary> PauseSessionAsync(CancellationToken cancellationToken = default) =>
        SendAsync<SessionSummary>(HttpMethod.Post, "sessions/current/pause", null, cancellationToken);

    public Task<SessionSummary> ResumeSessionAsync(CancellationToken cancellationToken = default) =>
        SendAsync<SessionSummary>(HttpMethod.Post, "sessions/current/resume", null, cancellationToken);

    public Task<SessionSummary> StopSessionAsync(CancellationToken cancellationToken = default) =>
        SendAsync<SessionSummary>(HttpMethod.Post, "sessions/current/stop", null, cancellationToken);

    public Task<SessionPage> ListSessionsAsync(
        int limit = 50, int offset = 0, CancellationToken cancellationToken = default) =>
        SendAsync<SessionPage>(
            HttpMethod.Get, $"sessions?limit={limit}&offset={offset}", null, cancellationToken);

    public Task<SessionDetail> GetSessionAsync(
        string id, CancellationToken cancellationToken = default) =>
        SendAsync<SessionDetail>(HttpMethod.Get, $"sessions/{Escape(id)}", null, cancellationToken);

    public Task<Transcript> GetTranscriptAsync(
        string id, CancellationToken cancellationToken = default) =>
        SendAsync<Transcript>(
            HttpMethod.Get, $"sessions/{Escape(id)}/transcript", null, cancellationToken);

    public Task<Minutes> GetMinutesAsync(string id, CancellationToken cancellationToken = default) =>
        SendAsync<Minutes>(HttpMethod.Get, $"sessions/{Escape(id)}/minutes", null, cancellationToken);

    public async Task RegenerateMinutesAsync(
        string id, CancellationToken cancellationToken = default)
    {
        using var response = await SendRawAsync(
            HttpMethod.Post, $"sessions/{Escape(id)}/minutes", new { }, cancellationToken);
    }

    public Task<EngineSettings> GetSettingsAsync(CancellationToken cancellationToken = default) =>
        SendAsync<EngineSettings>(HttpMethod.Get, "settings", null, cancellationToken);

    private async Task<T> SendAsync<T>(
        HttpMethod method, string path, object? body, CancellationToken cancellationToken)
    {
        using var response = await SendRawAsync(method, path, body, cancellationToken);
        var value = await response.Content.ReadFromJsonAsync<T>(EngineJson.Options, cancellationToken);
        return value ?? throw new JsonException($"Empty response from {path}");
    }

    private async Task<HttpResponseMessage> SendRawAsync(
        HttpMethod method, string path, object? body, CancellationToken cancellationToken)
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

        if (response.IsSuccessStatusCode)
        {
            return response;
        }

        using (response)
        {
            throw await ToExceptionAsync(response, cancellationToken);
        }
    }

    private static async Task<Exception> ToExceptionAsync(
        HttpResponseMessage response, CancellationToken cancellationToken)
    {
        var text = await response.Content.ReadAsStringAsync(cancellationToken);
        try
        {
            var envelope = JsonSerializer.Deserialize<ErrorEnvelope>(text, EngineJson.Options);
            if (envelope?.Error is { } error)
            {
                return new EngineApiException(response.StatusCode, error.Code, error.Message);
            }
        }
        catch (JsonException)
        {
            // Not the envelope (e.g. a proxy page): fall through to a generic error.
        }

        return new EngineApiException(
            response.StatusCode, "http_error", $"HTTP {(int)response.StatusCode}");
    }

    private static string Escape(string id) => Uri.EscapeDataString(id);

    private sealed record ErrorEnvelope(ErrorBody? Error);

    private sealed record ErrorBody(string Code, string Message);
}
