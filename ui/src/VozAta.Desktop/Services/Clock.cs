using System.Diagnostics.CodeAnalysis;
using Avalonia.Threading;

namespace VozAta.Desktop.Services;

/// <summary>The current time (tests move a fake clock by hand).</summary>
public interface IClock
{
    DateTimeOffset Now { get; }
}

[ExcludeFromCodeCoverage(Justification = "The system clock; tests use a fake.")]
public sealed class SystemClock : IClock
{
    public DateTimeOffset Now => DateTimeOffset.Now;
}

/// <summary>A periodic tick on the UI thread; dispose the result to stop it.</summary>
public interface IUiTimer
{
    IDisposable Start(TimeSpan interval, Action tick);
}

[ExcludeFromCodeCoverage(Justification = "Avalonia's DispatcherTimer; tests tick a fake.")]
public sealed class AvaloniaUiTimer : IUiTimer
{
    public IDisposable Start(TimeSpan interval, Action tick) => DispatcherTimer.Run(() =>
    {
        tick();
        return true;
    }, interval);
}
