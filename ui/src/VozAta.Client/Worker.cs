namespace VozAta.Client;

// The VozAta worker on another PC (api-contract rows tagged 47): discovery and pairing.

/// <summary>A worker that answered <c>GET /worker/discover</c>; no secret.</summary>
public sealed record FoundWorker(string Id, string Name, string Url, string Version, string? Gpu);

/// <summary><c>GET /worker/discover</c> answer.</summary>
public sealed record WorkersFound(IReadOnlyList<FoundWorker> Workers);

/// <summary><c>POST /worker/pair</c> answer: the engine saved its URL, token and id.</summary>
public sealed record PairedWorker(string? Id, string Name, string Url);
