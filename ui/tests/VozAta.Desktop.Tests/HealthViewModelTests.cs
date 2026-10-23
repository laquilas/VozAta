using VozAta.Client;
using VozAta.Desktop.Services;
using VozAta.Desktop.Tests.Fakes;
using VozAta.Desktop.ViewModels;

namespace VozAta.Desktop.Tests;

public sealed class HealthViewModelTests
{
    private readonly FakeEngineClient _client = new();
    private readonly LocalizationService _localization = new();

    private HealthViewModel Create() => new(_client, _localization);

    [Fact]
    public async Task Loading_describes_gpu_speech_and_minutes()
    {
        var health = Create();
        Assert.Equal(("", "", ""), (health.GpuText, health.SpeechText, health.MinutesText));

        await health.LoadAsync();

        Assert.Equal("GPU: RTX 3050 (6144 MB)", health.GpuText);
        Assert.Equal("Speech: large-v3 on auto", health.SpeechText);
        Assert.Equal("Minutes: qwen2.5:7b ready", health.MinutesText);
        Assert.Null(health.Error);
    }

    [Fact]
    public async Task Check_again_reports_changes_such_as_ollama_starting()
    {
        _client.Health = _client.Health with { Gpu = new GpuStatus(false, null, null), Llm = new LlmStatus("ollama", "qwen2.5:7b", false) };
        var health = Create();
        await health.LoadAsync();
        Assert.Equal("No GPU (CPU only)", health.GpuText);
        Assert.Equal("Minutes: qwen2.5:7b not reachable (start Ollama)", health.MinutesText);

        _client.Health = _client.Health with { Llm = new LlmStatus("ollama", "qwen2.5:7b", true) };
        await health.CheckAgainCommand.ExecuteAsync(null);

        Assert.Equal("Minutes: qwen2.5:7b ready", health.MinutesText);
    }

    [Fact]
    public async Task An_unreachable_engine_is_reported_and_the_texts_stay_empty()
    {
        _client.UnavailableHealthChecks = 1;
        var health = Create();

        await health.LoadAsync();

        Assert.Equal(_localization["EngineUnavailable"], health.Error);
        Assert.Equal("", health.GpuText);
        await health.CheckAgainCommand.ExecuteAsync(null);
        Assert.Null(health.Error);
    }

    [Fact]
    public async Task Texts_follow_the_ui_language()
    {
        var health = Create();
        await health.LoadAsync();

        _localization.SetLanguage("pt-BR");
        health.RefreshTexts();

        Assert.Equal("Fala: large-v3 em auto", health.SpeechText);
    }

    [Fact]
    public async Task The_worker_line_says_where_the_work_runs()
    {
        var health = Create();
        await health.LoadAsync();
        Assert.Null(health.WorkerText); // no worker set up

        _client.Health = _client.Health with { Worker = Worker("worker", "local") };
        await health.LoadAsync();
        Assert.Equal(("Worker: 192.168.0.30", false), (health.WorkerText, health.IsWorkerOff));

        _client.Health = _client.Health with { Worker = Worker("fallback", "local") };
        await health.LoadAsync();
        Assert.Equal(("This PC (worker off)", true), (health.WorkerText, health.IsWorkerOff));

        _client.Health = _client.Health with { Worker = Worker("local", "local") };
        await health.LoadAsync();
        Assert.False(health.HasWorkerText); // set up but no task uses it
    }

    private static WorkerHealth Worker(string speech, string translation) =>
        new("http://192.168.0.30:8766", speech != "fallback", "0.9.0",
            new Dictionary<string, string> { ["speech"] = speech, ["speakers"] = "local", ["translation"] = translation });
}
