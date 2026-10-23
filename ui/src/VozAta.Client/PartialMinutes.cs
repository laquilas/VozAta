namespace VozAta.Client;

// Minutes of part of a meeting (api-contract rows tagged 48): so far while recording, or a range.

/// <summary>One partial minutes, without its Markdown (the list).</summary>
public sealed record PartialMinutesSummary(
    string Id, string CreatedAt, double Start, double End, string Origin, string? Template);

/// <summary><c>GET /sessions/{id}/partial-minutes</c>: oldest first.</summary>
public sealed record PartialMinutesList(IReadOnlyList<PartialMinutesSummary> Items);

/// <summary><c>GET /sessions/{id}/partial-minutes/{pid}</c>.</summary>
public sealed record PartialMinutesDetail(
    string Id, string CreatedAt, double Start, double End, string Origin, string? Template, string Markdown);

/// <summary><c>POST /sessions/{id}/partial-minutes</c>: written in the background, then <see cref="PartialMinutesReadyEvent"/>.</summary>
public sealed record PartialMinutesStarted(string PartialId);

/// <summary>Partial minutes were written (<c>partial_minutes_ready</c>).</summary>
public sealed record PartialMinutesReadyEvent(string? SessionId, string PartialId, double Start, double End, string Origin)
    : EngineEvent(SessionId);
