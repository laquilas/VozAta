using VozAta.Desktop.Services;

namespace VozAta.Desktop.Tests;

/// <summary>
/// Manual smoke check of the real LibVLC player (phase 37): set <c>VOZATA_LIBVLC_URL</c> to a
/// running engine's <c>/sessions/{id}/audio/{track}</c> URL of a recording longer than 10 s. Skipped
/// otherwise (unit tests never touch audio hardware). The volume is 0.
/// </summary>
public sealed class LibVlcSmokeTests
{
    private static readonly string? Url = Environment.GetEnvironmentVariable("VOZATA_LIBVLC_URL");

    [Fact]
    public async Task The_engine_stream_plays_seeks_and_changes_speed()
    {
        if (string.IsNullOrEmpty(Url))
        {
            return; // manual check only
        }

        using var player = new LibVlcAudioPlayer();
        await player.OpenAsync(new Uri(Url));
        Assert.True(player.Duration > 10, $"duration {player.Duration}");
        player.Volume = 0;
        player.Seek(2);
        player.Play();
        await WaitAsync(() => player.IsPlaying && player.Position >= 2.5);

        player.Rate = 2;
        player.Seek(8);
        await WaitAsync(() => player.Position >= 9);
        Assert.Equal(2, player.Rate, 1);

        player.Pause();
        await WaitAsync(() => !player.IsPlaying);
        var paused = player.Position;
        await Task.Delay(500);
        Assert.Equal(paused, player.Position, 1);
    }

    private static async Task WaitAsync(Func<bool> condition)
    {
        for (var i = 0; i < 100 && !condition(); i++)
        {
            await Task.Delay(100);
        }

        Assert.True(condition());
    }
}
