using System.Diagnostics.CodeAnalysis;
using System.Runtime.InteropServices;

namespace VozAta.Desktop.Services;

/// <summary>Short sounds of the app (phase 59: a voice command was understood).</summary>
public interface ISoundPlayer
{
    void PlayChime();
}

/// <summary>Plays nothing (tests, and systems without a sound API).</summary>
public sealed class SilentSoundPlayer : ISoundPlayer
{
    public void PlayChime()
    {
    }
}

/// <summary>A short two-note chime, made in memory: 16-bit mono PCM in a WAV container.</summary>
public static class Chime
{
    public const int SampleRate = 22050;

    /// <summary>The WAV bytes: 880 Hz then 1320 Hz, 90 ms each, faded in and out.</summary>
    public static byte[] Wav()
    {
        var notes = new[] { 880.0, 1320.0 };
        var perNote = SampleRate * 90 / 1000;
        var samples = new short[perNote * notes.Length];
        for (var note = 0; note < notes.Length; note++)
        {
            for (var i = 0; i < perNote; i++)
            {
                var fade = Math.Min(1.0, Math.Min(i, perNote - i) / (perNote * 0.15));
                var value = Math.Sin(2 * Math.PI * notes[note] * i / SampleRate) * fade * 0.25;
                samples[(note * perNote) + i] = (short)(value * short.MaxValue);
            }
        }

        using var stream = new MemoryStream();
        using var writer = new BinaryWriter(stream);
        var data = samples.Length * 2;
        writer.Write("RIFF"u8);
        writer.Write(36 + data);
        writer.Write("WAVEfmt "u8);
        writer.Write(16);
        writer.Write((short)1);
        writer.Write((short)1);
        writer.Write(SampleRate);
        writer.Write(SampleRate * 2);
        writer.Write((short)2);
        writer.Write((short)16);
        writer.Write("data"u8);
        writer.Write(data);
        foreach (var sample in samples)
        {
            writer.Write(sample);
        }

        writer.Flush();
        return stream.ToArray();
    }
}

/// <summary>Windows: <c>PlaySound</c> of winmm from memory, asynchronously.</summary>
[ExcludeFromCodeCoverage(Justification = "Plays through the sound card; covered by the manual check.")]
public sealed class WindowsSoundPlayer : ISoundPlayer, IDisposable
{
    private const uint SndAsync = 0x0001;
    private const uint SndNoDefault = 0x0002;
    private const uint SndMemory = 0x0004;

    // pinned for as long as the player lives: PlaySound reads it while it plays
    private readonly GCHandle _chime = GCHandle.Alloc(Chime.Wav(), GCHandleType.Pinned);

    public void PlayChime()
    {
        if (OperatingSystem.IsWindows())
        {
            PlaySound(_chime.AddrOfPinnedObject(), IntPtr.Zero, SndAsync | SndNoDefault | SndMemory);
        }
    }

    public void Dispose()
    {
        if (OperatingSystem.IsWindows())
        {
            PlaySound(IntPtr.Zero, IntPtr.Zero, 0);
        }

        _chime.Free();
    }

    // DllImport, not LibraryImport: no unsafe code in the project for one call
    [DllImport("winmm.dll", EntryPoint = "PlaySoundW", CharSet = CharSet.Unicode)]
    [return: MarshalAs(UnmanagedType.Bool)]
    private static extern bool PlaySound(IntPtr sound, IntPtr module, uint flags);
}
