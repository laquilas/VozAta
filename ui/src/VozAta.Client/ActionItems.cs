namespace VozAta.Client;

// Action items (api-contract rows tagged 23): extract, list, edit and export as work items / issues.

/// <summary>A task agreed in a meeting; <see cref="ExportedUrl"/> is set once it was exported.</summary>
public sealed record ActionItem(
    string Id,
    string Description,
    string? Owner,
    string? Due,
    IReadOnlyList<string> SourceSegmentIds,
    string? ExportedUrl);

/// <summary><c>GET|PUT /sessions/{id}/action-items</c>: the items and the configured export targets.</summary>
public sealed record ActionItemList(IReadOnlyList<ActionItem> Items, IReadOnlyList<string> Targets);

/// <summary>One edited item of <c>PUT /sessions/{id}/action-items</c>.</summary>
public sealed record ActionItemEdit(string Id, string Description, string? Owner, string? Due);

/// <summary>A created work item / issue.</summary>
public sealed record CreatedTask(string ItemId, string Url);

/// <summary>An item that was not exported, with the engine's localized reason.</summary>
public sealed record FailedTask(string ItemId, string Error);

/// <summary><c>POST /sessions/{id}/action-items/export</c> answer.</summary>
public sealed record ActionItemsExportResult(IReadOnlyList<CreatedTask> Created, IReadOnlyList<FailedTask> Failed);

/// <summary>Action items were extracted for a session (at stop or on request).</summary>
public sealed record ActionItemsReadyEvent(string? SessionId, int Count) : EngineEvent(SessionId);
