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

    public EngineRestartResult RestartResult { get; set; } = EngineRestartResult.Restarted;

    public int Restarts { get; private set; }

    public Task<EngineRestartResult> RestartAsync(CancellationToken cancellationToken = default)
    {
        Restarts++;
        return Task.FromResult(RestartResult);
    }
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

/// <summary>A clock the test moves by hand.</summary>
internal sealed class FakeClock : IClock
{
    public DateTimeOffset Now { get; private set; } = new(2026, 10, 16, 9, 0, 0, TimeSpan.Zero);

    public void Advance(TimeSpan by) => Now += by;
}

/// <summary>A timer the test ticks by hand.</summary>
internal sealed class FakeTimer : IUiTimer
{
    private readonly List<Action> _ticks = [];

    public TimeSpan? Interval { get; private set; }

    public int Running => _ticks.Count;

    public IDisposable Start(TimeSpan interval, Action tick)
    {
        Interval = interval;
        _ticks.Add(tick);
        return new Subscription(() => _ticks.Remove(tick));
    }

    public void Tick()
    {
        foreach (var tick in _ticks.ToList())
        {
            tick();
        }
    }

    private sealed class Subscription(Action dispose) : IDisposable
    {
        public void Dispose() => dispose();
    }
}

/// <summary>In-memory preferences; counts saves.</summary>
internal sealed class FakePreferences : IUiPreferences
{
    public UiPreferencesData Data { get; set; } = new();

    public int Saves { get; private set; }

    public UiPreferencesData Load() => Data;

    public void Save(UiPreferencesData preferences)
    {
        Data = preferences;
        Saves++;
    }
}

/// <summary>Records the paths it was asked to open.</summary>
internal sealed class FakeShell : IShellService
{
    public List<string> Opened { get; } = [];

    public void Open(string path) => Opened.Add(path);
}

/// <summary>Records saves; answers with <see cref="Path"/> (null = the user cancelled).</summary>
internal sealed class FakeFileSaver : IFileSaver
{
    public string? Path { get; set; } = @"C:\Users\me\Documents\minutes.pdf";

    public List<(string Name, string TypeName, string Extension, byte[] Content)> Saves { get; } = [];

    public Task<string?> SaveAsync(string suggestedName, string typeName, string extension, byte[] content)
    {
        Saves.Add((suggestedName, typeName, extension, content));
        return Task.FromResult(Path);
    }
}
