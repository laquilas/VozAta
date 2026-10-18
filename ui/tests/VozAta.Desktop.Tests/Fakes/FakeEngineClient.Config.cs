using VozAta.Client;

namespace VozAta.Desktop.Tests.Fakes;

/// <summary>Config page (phase 38): option lists, scripted connection tests, the audio cache.</summary>
internal sealed partial class FakeEngineClient
{
    public SettingOptions Options { get; set; } = SettingOptions.Empty;

    public Exception? OptionsError { get; set; }

    /// <summary>Target → answer; a missing target answers "ok".</summary>
    public Dictionary<string, ConnectionTestResult> TestResults { get; } = [];

    public List<string> Tests { get; } = [];

    public Exception? TestError { get; set; }

    /// <summary>When set, connection tests wait for it (tests look at the running state).</summary>
    public TaskCompletionSource? TestGate { get; set; }

    public Exception? ClearCacheError { get; set; }

    public Task<SettingOptions> GetSettingOptionsAsync(CancellationToken cancellationToken = default)
    {
        Calls.Add("options");
        return OptionsError is null ? Task.FromResult(Options) : Task.FromException<SettingOptions>(OptionsError);
    }

    public async Task<ConnectionTestResult> TestConnectionAsync(string target, CancellationToken cancellationToken = default)
    {
        Calls.Add($"test {target}");
        Tests.Add(target);
        if (TestGate is not null)
        {
            await TestGate.Task;
        }

        if (TestError is not null)
        {
            throw TestError;
        }

        return TestResults.GetValueOrDefault(target) ?? new ConnectionTestResult(true, $"{target} ok");
    }

    public Task<CacheCleared> ClearAudioCacheAsync(CancellationToken cancellationToken = default)
    {
        Calls.Add("clear-cache");
        if (ClearCacheError is not null)
        {
            return Task.FromException<CacheCleared>(ClearCacheError);
        }

        var freed = Health.Storage?.AudioCacheBytes ?? 0;
        if (Health.Storage is { } storage)
        {
            Health = Health with { Storage = storage with { AudioCacheBytes = 0 } };
        }

        return Task.FromResult(new CacheCleared(freed));
    }
}
