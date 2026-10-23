using VozAta.Client;

namespace VozAta.Desktop.Tests.Fakes;

/// <summary>The VozAta worker (phase 47): scripted discovery and pairing.</summary>
internal sealed partial class FakeEngineClient
{
    public List<FoundWorker> FoundWorkers { get; } = [];

    public Exception? DiscoverError { get; set; }

    public Exception? PairError { get; set; }

    /// <summary>Every pairing asked for, as (url, code).</summary>
    public List<(string Url, string Code)> Pairings { get; } = [];

    public Task<WorkersFound> DiscoverWorkersAsync(CancellationToken cancellationToken = default)
    {
        Calls.Add("discover-workers");
        return DiscoverError is null
            ? Task.FromResult(new WorkersFound([.. FoundWorkers]))
            : Task.FromException<WorkersFound>(DiscoverError);
    }

    /// <summary>Like the engine: a paired worker's address, token (masked) and id become saved settings.</summary>
    public Task<PairedWorker> PairWorkerAsync(string url, string code, CancellationToken cancellationToken = default)
    {
        Calls.Add($"pair-worker {url}");
        Pairings.Add((url, code));
        if (PairError is not null)
        {
            return Task.FromException<PairedWorker>(PairError);
        }

        var worker = FoundWorkers.FirstOrDefault(found => found.Url == url);
        SettingValues["WORKER_URL"] = url;
        SettingValues["WORKER_TOKEN"] = "********";
        SettingValues["WORKER_ID"] = worker?.Id;
        return Task.FromResult(new PairedWorker(worker?.Id, worker?.Name ?? url, url));
    }
}
