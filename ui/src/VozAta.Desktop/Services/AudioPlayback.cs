using VozAta.Client;

namespace VozAta.Desktop.Services;

/// <summary>
/// Plays a session track in the default player (phase 32, until the in-app player of phase 37):
/// downloads <c>GET /sessions/{id}/audio/{track}</c> to <c>&lt;folder&gt;\&lt;id&gt;-&lt;track&gt;.wav</c> and opens it.
/// Works for both storage backends, since the engine serves the audio of each.
/// </summary>
public static class AudioPlayback
{
    /// <summary>Where downloaded tracks go by default: <c>%TEMP%\VozAta\audio</c>.</summary>
    public static string DefaultFolder { get; } = Path.Combine(Path.GetTempPath(), "VozAta", "audio");

    /// <summary>
    /// Download and open the track. A file the player still holds is opened again as it is. A
    /// failed download deletes the partial file and rethrows (<see cref="EngineApiException"/>,
    /// <see cref="EngineUnavailableException"/>, <see cref="IOException"/>, <see cref="UnauthorizedAccessException"/>).
    /// </summary>
    public static async Task OpenAsync(
        IEngineClient client, IShellService shell, string folder, string sessionId, string track,
        CancellationToken cancellationToken = default)
    {
        var path = Path.Combine(folder, $"{sessionId}-{track}.wav");
        Directory.CreateDirectory(folder);
        FileStream file;
        try
        {
            file = new FileStream(path, FileMode.Create, FileAccess.Write, FileShare.None);
        }
        catch (IOException) when (File.Exists(path))
        {
            shell.Open(path); // in use by the player: already downloaded
            return;
        }

        try
        {
            await using (file)
            {
                await client.DownloadAudioAsync(sessionId, track, file, cancellationToken);
            }
        }
        catch
        {
            TryDelete(path);
            throw;
        }

        shell.Open(path);
    }

    /// <summary>Whether a failure of <see cref="OpenAsync"/> is one to show to the user.</summary>
    public static bool IsExpected(Exception error) =>
        error is EngineApiException or EngineUnavailableException or IOException or UnauthorizedAccessException;

    private static void TryDelete(string path)
    {
        try
        {
            File.Delete(path);
        }
        catch (Exception error) when (error is IOException or UnauthorizedAccessException)
        {
            // Left for the next download to overwrite.
        }
    }
}
