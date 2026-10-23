namespace VozAta.Client;

// The request history of a meeting (api-contract rows tagged 59).

/// <summary>
/// One request made on a meeting: a voice command, or minutes so far / of a range / again,
/// action items or a question. <see cref="Kind"/>: <c>minutes_so_far</c> | <c>range_minutes</c> |
/// <c>minutes</c> | <c>action_items</c> | <c>ask</c>; <see cref="Source"/>: <c>voice</c> | <c>button</c> |
/// <c>range</c> | <c>app</c>; <see cref="Status"/>: <c>recognized</c> | <c>running</c> | <c>done</c> |
/// <c>failed</c> | <c>ignored</c>. <see cref="At"/> is the meeting second while recording;
/// <see cref="ResultId"/> the partial minutes or the answer; <see cref="Message"/> an error code.
/// </summary>
public sealed record RequestEntry(
    string Id,
    string CreatedAt,
    double? At,
    string Kind,
    string Source,
    string Text,
    string Status,
    string? ResultId,
    string? Message,
    string? FinishedAt)
{
    public bool IsFinished => Status is "done" or "failed" or "ignored";
}

/// <summary><c>GET /sessions/{id}/requests</c>: oldest first.</summary>
public sealed record RequestList(IReadOnlyList<RequestEntry> Items);

/// <summary>A request of the meeting started or changed (<c>request_updated</c>).</summary>
public sealed record RequestUpdatedEvent(string? SessionId, RequestEntry Request) : EngineEvent(SessionId);
