using System.Net;
using System.Text.Json;
using System.Threading.Channels;
using VozAta.Client;
using VozAta.Desktop.Services;

namespace VozAta.Desktop.Tests.Fakes;

/// <summary>The recorder process API (phase 61), recording what was asked.</summary>
internal sealed class FakeRecorderClient : IRecorderClient
{
    public List<string> Calls { get; } = [];

    public List<StartRecordingRequest> Starts { get; } = [];

    public List<IReadOnlyDictionary<string, object?>> OptionUpdates { get; } = [];

    public Exception? StartError { get; set; }

    public Exception? OptionsError { get; set; }

    public string RecordingId { get; set; } = "20261103_101500";

    public Task<RecorderHealth> GetHealthAsync(CancellationToken cancellationToken = default)
    {
        Calls.Add("health");
        return Task.FromResult(new RecorderHealth("ok", "0.3.1", null));
    }

    public Task<DeviceList> GetDevicesAsync(CancellationToken cancellationToken = default) =>
        Task.FromResult(new DeviceList([], [], null, null));

    public Task<RecordingSummary> StartAsync(StartRecordingRequest request, CancellationToken cancellationToken = default)
    {
        Calls.Add("start");
        Starts.Add(request);
        return StartError is { } error
            ? Task.FromException<RecordingSummary>(error)
            : Task.FromResult(new RecordingSummary(RecordingId, "recording"));
    }

    public Task<RecordingSummary> PauseAsync(CancellationToken cancellationToken = default) => Control("pause", "paused");

    public Task<RecordingSummary> ResumeAsync(CancellationToken cancellationToken = default) => Control("resume", "recording");

    public Task<RecordingSummary> StopAsync(CancellationToken cancellationToken = default) => Control("stop", "stopped");

    public Task<RecordingSummary> UpdateOptionsAsync(
        IReadOnlyDictionary<string, object?> options, CancellationToken cancellationToken = default)
    {
        Calls.Add("options");
        OptionUpdates.Add(options);
        return OptionsError is { } error
            ? Task.FromException<RecordingSummary>(error)
            : Task.FromResult(new RecordingSummary(RecordingId, "recording"));
    }

    public List<(string SourceId, string Mode)> ModeChanges { get; } = [];

    public Exception? SourcesError { get; set; }

    public List<RecordingSource> SourceItems { get; } = [];

    public Task<RecordingSources> GetSourcesAsync(CancellationToken cancellationToken = default) =>
        Task.FromResult(new RecordingSources(RecordingId, [.. SourceItems]));

    public Task<RecordingSources> SetSourceModeAsync(
        string sourceId, string mode, CancellationToken cancellationToken = default)
    {
        Calls.Add("source_mode");
        ModeChanges.Add((sourceId, mode));
        if (SourcesError is { } error)
        {
            return Task.FromException<RecordingSources>(error);
        }

        var index = SourceItems.FindIndex(item => item.Id == sourceId);
        if (index >= 0)
        {
            SourceItems[index] = SourceItems[index] with { Mode = mode, Selected = mode == "on" || (mode == "auto" && SourceItems[index].Selected) };
        }

        return Task.FromResult(new RecordingSources(RecordingId, [.. SourceItems]));
    }

    private Task<RecordingSummary> Control(string call, string status)
    {
        Calls.Add(call);
        return Task.FromResult(new RecordingSummary(RecordingId, status));
    }

    public static EngineApiException ApiError(string code) => new(HttpStatusCode.ServiceUnavailable, code, code);

    public static IReadOnlyDictionary<string, JsonElement> Options(string json) =>
        JsonSerializer.Deserialize<Dictionary<string, JsonElement>>(json)!;
}

internal sealed class FakeRecorderEvents : IRecorderEvents
{
    private readonly Channel<RecorderEvent> _events = Channel.CreateUnbounded<RecorderEvent>();

    public void Send(RecorderEvent recorderEvent) => _events.Writer.TryWrite(recorderEvent);

    public async IAsyncEnumerable<RecorderEvent> ReadAllAsync(
        [System.Runtime.CompilerServices.EnumeratorCancellation] CancellationToken cancellationToken = default)
    {
        await foreach (var recorderEvent in _events.Reader.ReadAllAsync(cancellationToken))
        {
            yield return recorderEvent;
        }
    }
}

internal sealed class FakeRecorderProcess : IRecorderProcess
{
    public RecorderStartResult Result { get; set; } = RecorderStartResult.AlreadyRunning;

    public int Starts { get; private set; }

    public Task<RecorderStartResult> EnsureRunningAsync(CancellationToken cancellationToken = default)
    {
        Starts++;
        return Task.FromResult(Result);
    }
}
