using System.Runtime.CompilerServices;
using System.Threading.Channels;
using VozAta.Client;
using VozAta.Desktop.Services;

namespace VozAta.Desktop.Tests.Fakes;

/// <summary>Runs posted work at once (tests are single-threaded where it matters).</summary>
internal sealed class ImmediateDispatcher : IUiDispatcher
{
    public void Post(Action action) => action();
}

/// <summary>An event stream the test feeds by hand.</summary>
internal sealed class FakeEngineEvents : IEngineEvents
{
    private readonly Channel<EngineEvent> _events = Channel.CreateUnbounded<EngineEvent>();

    public void Send(EngineEvent engineEvent) => _events.Writer.TryWrite(engineEvent);

    public void Complete() => _events.Writer.TryComplete();

    public async IAsyncEnumerable<EngineEvent> ReadAllAsync(
        [EnumeratorCancellation] CancellationToken cancellationToken = default)
    {
        await foreach (var engineEvent in _events.Reader.ReadAllAsync(cancellationToken))
        {
            yield return engineEvent;
        }
    }
}

internal sealed class FakeEngineProcess : IEngineProcess
{
    public EngineStartResult Result { get; set; } = EngineStartResult.AlreadyRunning;

    public int Stops { get; private set; }

    public Task<EngineStartResult> EnsureRunningAsync(CancellationToken cancellationToken = default) =>
        Task.FromResult(Result);

    public void StopIfStarted() => Stops++;
}

internal sealed class FakeDialogs : IDialogService
{
    public bool Answer { get; set; } = true;

    public List<string> Asked { get; } = [];

    public Task<bool> ConfirmAsync(string title, string message, string confirm, string cancel)
    {
        Asked.Add(title);
        return Task.FromResult(Answer);
    }
}
