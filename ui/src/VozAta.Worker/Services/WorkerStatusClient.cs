using System.Net.Http.Json;
using System.Text.Json;
using System.Text.Json.Serialization;

namespace VozAta.Worker.Services;

public sealed record WorkerGpu(bool Available, string? Name);

/// <summary>The worker's <c>GET /local/status</c> (phase 47), answered to this PC only.</summary>
public sealed record LocalStatus(
    string Version,
    string? Id,
    string Name,
    int Port,
    IReadOnlyList<string> Addresses,
    string? Token,
    string? PairingCode,
    int? CodeExpiresIn,
    WorkerGpu Gpu,
    IReadOnlyList<string> Models);

public interface IWorkerStatusClient
{
    /// <summary>The status, or null while the worker does not answer (starting, stopped).</summary>
    Task<LocalStatus?> GetAsync(int port, CancellationToken cancellationToken = default);
}

public sealed class WorkerStatusClient(HttpClient http) : IWorkerStatusClient
{
    private static readonly JsonSerializerOptions Json = new(JsonSerializerDefaults.Web)
    {
        PropertyNamingPolicy = JsonNamingPolicy.SnakeCaseLower,
        NumberHandling = JsonNumberHandling.Strict,
    };

    public async Task<LocalStatus?> GetAsync(int port, CancellationToken cancellationToken = default)
    {
        try
        {
            return await http.GetFromJsonAsync<LocalStatus>($"http://127.0.0.1:{port}/local/status", Json, cancellationToken);
        }
        catch (Exception error) when (error is HttpRequestException or TaskCanceledException or JsonException)
        {
            return null;
        }
    }
}
