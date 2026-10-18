namespace VozAta.Client;

// Config page (api-contract rows tagged 38): option lists, connection tests and storage.

/// <summary>One entry of a <c>GET /settings/options</c> list; <see cref="Available"/> is false for a model not downloaded yet.</summary>
public sealed record SettingOption(string Value, string Label, bool Available = true);

/// <summary><c>GET /settings/options</c>: lists by <c>options_source</c>; <see cref="Reachable"/> is false for a service that did not answer.</summary>
public sealed record SettingOptions(
    IReadOnlyDictionary<string, IReadOnlyList<SettingOption>> Options,
    IReadOnlyDictionary<string, bool> Reachable)
{
    public static SettingOptions Empty { get; } = new(
        new Dictionary<string, IReadOnlyList<SettingOption>>(), new Dictionary<string, bool>());
}

/// <summary>The services <c>POST /settings/test/{target}</c> can check.</summary>
public static class ConnectionTargets
{
    public const string Ollama = "ollama";
    public const string SttApi = "stt_api";
    public const string HfToken = "hf_token";
    public const string AzureDevOps = "azure_devops";
    public const string GitHub = "github";
}

/// <summary><c>POST /settings/test/{target}</c>: the engine's localized message (never a secret).</summary>
public sealed record ConnectionTestResult(bool Ok, string Message);

/// <summary>
/// <c>GET /health</c> <c>storage</c>: backend, database path (31), the OneDrive warning, and the
/// database and audio cache sizes (38).
/// </summary>
public sealed record StorageStatus(
    string Backend,
    string? Database,
    string? Warning,
    long? SizeBytes = null,
    long AudioCacheBytes = 0);

/// <summary><c>DELETE /storage/cache</c> answer.</summary>
public sealed record CacheCleared(long FreedBytes);
