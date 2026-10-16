using CommunityToolkit.Mvvm.ComponentModel;
using VozAta.Desktop.Services;

namespace VozAta.Desktop.ViewModels;

/// <summary>
/// One channel's level meter: <see cref="Level"/> and <see cref="Peak"/> in 0…1 for −60…0 dBFS.
/// A louder reading shows at once; on <see cref="Tick"/> the bar falls at
/// <see cref="FallPerSecond"/> (never below the latest reading) and the peak marker holds for
/// <see cref="PeakHold"/> before falling. A watched channel (system audio) raises
/// <see cref="NoSignal"/> after <see cref="NoSignalAfter"/> without sound while recording.
/// </summary>
public sealed partial class LevelMeterViewModel(IClock clock, bool watchSilence) : ObservableObject
{
    public const double FloorDb = -60;
    public const double FallPerSecond = 1.5;
    public static readonly TimeSpan PeakHold = TimeSpan.FromSeconds(1);
    public static readonly TimeSpan NoSignalAfter = TimeSpan.FromSeconds(30);

    private double _reading;
    private DateTimeOffset _peakAt;
    private DateTimeOffset _heardAt;
    private DateTimeOffset _tickedAt = clock.Now;
    private bool _active;

    [ObservableProperty]
    public partial double Level { get; private set; }

    [ObservableProperty]
    public partial double Peak { get; private set; }

    [ObservableProperty]
    public partial bool NoSignal { get; private set; }

    [ObservableProperty]
    public partial string Label { get; set; } = "";

    public static double Normalize(double rmsDb) => Math.Clamp((rmsDb - FloorDb) / -FloorDb, 0, 1);

    /// <summary>A recording started: reset and start watching for silence.</summary>
    public void Begin()
    {
        Reset();
        SetActive(true);
    }

    /// <summary>The recording ended: empty meter, no hint.</summary>
    public void End()
    {
        Reset();
        _active = false;
    }

    /// <summary>Recording (true) or paused (false); the silence count restarts when it resumes.</summary>
    public void SetActive(bool active)
    {
        if (active && !_active)
        {
            _heardAt = clock.Now;
        }

        _active = active;
        if (!active)
        {
            NoSignal = false;
        }
    }

    public void OnLevel(double rmsDb)
    {
        var now = clock.Now;
        _reading = Normalize(rmsDb);
        if (_reading > Level)
        {
            Level = _reading;
        }

        if (_reading >= Peak)
        {
            Peak = _reading;
            _peakAt = now;
        }

        if (rmsDb > FloorDb)
        {
            _heardAt = now;
            NoSignal = false;
        }
    }

    public void Tick()
    {
        var now = clock.Now;
        var fall = FallPerSecond * (now - _tickedAt).TotalSeconds;
        _tickedAt = now;
        Level = Math.Max(_reading, Level - fall);
        if (now - _peakAt > PeakHold)
        {
            Peak = Math.Max(Level, Peak - fall);
        }

        if (watchSilence && _active && now - _heardAt >= NoSignalAfter)
        {
            NoSignal = true;
        }
    }

    private void Reset()
    {
        _reading = 0;
        Level = 0;
        Peak = 0;
        NoSignal = false;
        _tickedAt = clock.Now;
    }
}
