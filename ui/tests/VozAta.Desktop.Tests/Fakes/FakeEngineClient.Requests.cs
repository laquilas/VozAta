using VozAta.Client;

namespace VozAta.Desktop.Tests.Fakes;

/// <summary>The request history of each meeting (phase 59).</summary>
internal sealed partial class FakeEngineClient
{
    /// <summary>By session id, oldest first.</summary>
    public Dictionary<string, List<RequestEntry>> Requests { get; } = [];

    public Exception? RequestsError { get; set; }

    public Task<RequestList> GetRequestsAsync(string sessionId, CancellationToken cancellationToken = default)
    {
        Calls.Add($"requests {sessionId}");
        if (RequestsError is not null)
        {
            return Task.FromException<RequestList>(RequestsError);
        }

        return Task.FromResult(new RequestList(Requests.TryGetValue(sessionId, out var items) ? [.. items] : []));
    }
}
