using System.Net;
using System.Text.Json;
using VozAta.Client;
using VozAta.Desktop.Services;
using VozAta.Desktop.Tests.Fakes;
using VozAta.Desktop.ViewModels;

namespace VozAta.Desktop.Tests;

public sealed class WorkerPairingViewModelTests
{
    private static readonly FoundWorker GpuPc = new("4f1c", "GPU-PC", "http://192.168.0.20:8766", "0.9.0", "RTX 4070");

    private readonly FakeEngineClient _client = new();
    private readonly LocalizationService _localization = new();

    private WorkerPairingViewModel Pairing() => new(_client, _localization);

    [Fact]
    public async Task Finding_lists_the_workers_with_their_address_version_and_gpu()
    {
        _client.FoundWorkers.Add(GpuPc);
        _client.FoundWorkers.Add(GpuPc with { Id = "b", Name = "Laptop", Url = "http://10.0.0.8:8766", Gpu = null });
        var pairing = Pairing();

        await pairing.FindCommand.ExecuteAsync(null);

        Assert.Equal(["GPU-PC", "Laptop"], pairing.Workers.Select(worker => worker.Name));
        Assert.Equal("http://192.168.0.20:8766 · VozAta 0.9.0 · RTX 4070", pairing.Workers[0].Detail);
        Assert.EndsWith(_localization["WorkerNoGpu"], pairing.Workers[1].Detail);
        Assert.Equal(_localization["WorkerTypeCode"], pairing.Message);
        Assert.False(pairing.IsSearching);
    }

    [Fact]
    public async Task Finding_nothing_says_what_to_check()
    {
        var pairing = Pairing();

        await pairing.FindCommand.ExecuteAsync(null);

        Assert.Empty(pairing.Workers);
        Assert.Equal(_localization["WorkerNoneFound"], pairing.Message);
    }

    [Fact]
    public async Task A_new_search_replaces_the_list()
    {
        _client.FoundWorkers.Add(GpuPc);
        var pairing = Pairing();
        await pairing.FindCommand.ExecuteAsync(null);
        _client.FoundWorkers.Clear();

        await pairing.FindCommand.ExecuteAsync(null);

        Assert.Empty(pairing.Workers);
    }

    [Fact]
    public async Task An_engine_that_is_off_is_shown()
    {
        _client.DiscoverError = new EngineUnavailableException("refused", new HttpRequestException());
        var pairing = Pairing();

        await pairing.FindCommand.ExecuteAsync(null);

        Assert.Equal(_localization["EngineUnavailable"], pairing.Error);
        Assert.Null(pairing.Message);
    }

    [Fact]
    public async Task Pairing_needs_a_code_then_saves_and_tells_the_page()
    {
        _client.FoundWorkers.Add(GpuPc);
        PairedWorker? told = null;
        var pairing = Pairing();
        pairing.Paired = paired => { told = paired; return Task.CompletedTask; };
        await pairing.FindCommand.ExecuteAsync(null);
        var worker = pairing.Workers[0];
        Assert.False(worker.PairCommand.CanExecute(null));

        worker.Code = " 123456 ";
        await worker.PairCommand.ExecuteAsync(null);

        Assert.Equal([("http://192.168.0.20:8766", "123456")], _client.Pairings);
        Assert.Equal(new PairedWorker("4f1c", "GPU-PC", "http://192.168.0.20:8766"), told);
        Assert.Equal(_localization.Format("WorkerPaired", "GPU-PC"), pairing.Message);
        Assert.Equal("", worker.Code);
        Assert.False(worker.IsPairing);
    }

    [Fact]
    public async Task A_refused_code_shows_the_engine_message()
    {
        _client.FoundWorkers.Add(GpuPc);
        _client.PairError = new EngineApiException(HttpStatusCode.Conflict, "worker_pairing_refused", "The worker refused the code.");
        var pairing = Pairing();
        await pairing.FindCommand.ExecuteAsync(null);
        var worker = pairing.Workers[0];
        worker.Code = "000000";

        await worker.PairCommand.ExecuteAsync(null);

        Assert.Equal("The worker refused the code.", pairing.Error);
        Assert.Equal("000000", worker.Code); // kept, so a typo can be fixed
    }

    [Fact]
    public async Task The_worker_group_pairs_and_shows_the_saved_address_and_id()
    {
        _client.Schema.Add(new SettingSchema("WORKER_URL", "url", JsonSerializer.SerializeToElement<string?>(null), null, false, "worker", "next_session", null));
        _client.Schema.Add(new SettingSchema("WORKER_TOKEN", "string", JsonSerializer.SerializeToElement<string?>(null), null, true, "worker", "next_session", null));
        _client.Schema.Add(new SettingSchema("WORKER_ID", "string", JsonSerializer.SerializeToElement<string?>(null), null, false, "worker", "next_session", null));
        _client.Schema.Add(new SettingSchema("MIX_MODE", "choice", JsonSerializer.SerializeToElement("mono"), ["mono", "stereo"], false, "audio", "next_session", null));
        _client.FoundWorkers.Add(GpuPc);
        var settings = new SettingsViewModel(_client, new FakeEngineProcess(), _localization);
        await settings.LoadAsync();
        var group = settings.Groups.Single(group => group.Id == "worker");
        Assert.False(settings.Groups.Single(group => group.Id == "audio").HasPairing);

        await group.Pairing!.FindCommand.ExecuteAsync(null);
        group.Pairing.Workers[0].Code = "123456";
        await group.Pairing.Workers[0].PairCommand.ExecuteAsync(null);

        var url = settings.Editors.Single(editor => editor.Key == "WORKER_URL");
        Assert.Equal("http://192.168.0.20:8766", url.TextValue);
        Assert.Equal("4f1c", settings.Editors.Single(editor => editor.Key == "WORKER_ID").TextValue);
        Assert.False(settings.IsDirty); // saved by the engine, nothing left to save
    }
}
