using VozAta.Client;

namespace VozAta.Desktop.Tests.Fakes;

/// <summary>Partial minutes (phase 48): stored per session; starting one is recorded, not written.</summary>
internal sealed partial class FakeEngineClient
{
    /// <summary>By session id, oldest first.</summary>
    public Dictionary<string, List<PartialMinutesDetail>> PartialMinutes { get; } = [];

    /// <summary>Every request, as (session id, start, end, template).</summary>
    public List<(string SessionId, double? Start, double? End, string? Template)> PartialRequests { get; } = [];

    public Exception? PartialMinutesError { get; set; }

    public Task<PartialMinutesStarted> StartPartialMinutesAsync(
        string sessionId, double? fromSeconds = null, double? toSeconds = null, string? templateId = null,
        CancellationToken cancellationToken = default)
    {
        Calls.Add($"partial-minutes {sessionId}");
        PartialRequests.Add((sessionId, fromSeconds, toSeconds, templateId));
        return PartialMinutesError is null
            ? Task.FromResult(new PartialMinutesStarted($"p{PartialRequests.Count}"))
            : Task.FromException<PartialMinutesStarted>(PartialMinutesError);
    }

    public Task<PartialMinutesList> GetPartialMinutesAsync(string sessionId, CancellationToken cancellationToken = default) =>
        Task.FromResult(new PartialMinutesList(
            [.. Stored(sessionId).Select(item => new PartialMinutesSummary(
                item.Id, item.CreatedAt, item.Start, item.End, item.Origin, item.Template))]));

    public Task<PartialMinutesDetail> GetPartialMinutesItemAsync(
        string sessionId, string partialId, CancellationToken cancellationToken = default) =>
        Stored(sessionId).FirstOrDefault(item => item.Id == partialId) is { } found
            ? Task.FromResult(found)
            : Task.FromException<PartialMinutesDetail>(
                new EngineApiException(System.Net.HttpStatusCode.NotFound, "partial_minutes_not_found", "Not found."));

    public Task DeletePartialMinutesAsync(string sessionId, string partialId, CancellationToken cancellationToken = default)
    {
        Calls.Add($"delete-partial {partialId}");
        Stored(sessionId).RemoveAll(item => item.Id == partialId);
        return Task.CompletedTask;
    }

    private List<PartialMinutesDetail> Stored(string sessionId) =>
        PartialMinutes.TryGetValue(sessionId, out var items) ? items : PartialMinutes[sessionId] = [];
}
