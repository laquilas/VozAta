using VozAta.Client;
using VozAta.Desktop.Services;
using VozAta.Desktop.Tests.Fakes;
using VozAta.Desktop.ViewModels;

namespace VozAta.Desktop.Tests;

/// <summary>The session page of phase 39: export the recording as a ZIP, delete the audio.</summary>
public sealed class SessionPageBundleTests : IDisposable
{
    private const string Id = "20261016_090000";

    private readonly FakeEngineClient _client = new();
    private readonly LocalizationService _localization = new();
    private readonly FakeFileSaver _saver = new() { Path = @"C:\Users\me\Documents\meeting.zip" };
    private readonly FakeDialogs _dialogs = new();
    private readonly FakeAudioPlayer _player = new() { Duration = 75 };

    public SessionPageBundleTests()
    {
        _client.Details[Id] = Detail(new Dictionary<string, double> { ["mic"] = 75, ["system"] = 75, ["mixed"] = 75 });
        _client.Transcripts[Id] = new Transcript("raw",
        [
            new Segment("mic-000001", "mic", "mic", "Me", 2.4, 4, "Good morning.", false, []),
        ]);
    }

    public void Dispose() => _player.Dispose();

    private static SessionDetail Detail(IReadOnlyDictionary<string, double>? audio) =>
        new(Id, "done", null, null, 75, "pt", false, null, null, audio);

    private SessionPageViewModel Create(string status = "done", IDialogService? dialogs = null) =>
        new(_client, new FakeShell(), _localization, _saver,
            new SessionSummary(Id, status, new DateTimeOffset(2026, 10, 16, 9, 0, 0, TimeSpan.Zero), null, 75, "pt", false, "Weekly"),
            dialogs: dialogs ?? _dialogs)
        {
            Players = (id, tracks) => new PlayerBarViewModel(
                _player, new ImmediateDispatcher(), track => new Uri($"http://engine/sessions/{id}/audio/{track}"), tracks, _localization),
        };

    [Fact]
    public async Task The_recording_is_streamed_into_the_file_the_user_chooses()
    {
        var page = Create();

        await page.ExportBundleCommand.ExecuteAsync(null);

        Assert.Equal([Id], _client.BundleDownloads);
        var (name, type, extension, content) = _saver.StreamSaves.Single();
        Assert.Equal(($"{Id}.zip", "ZIP archive", "zip"), (name, type, extension));
        Assert.Equal("PK"u8.ToArray(), content);
        Assert.Equal(@"Saved to C:\Users\me\Documents\meeting.zip", page.Message);
        Assert.False(page.IsExporting);
    }

    [Fact]
    public async Task A_cancelled_save_downloads_nothing()
    {
        _saver.Path = null;
        var page = Create();

        await page.ExportBundleCommand.ExecuteAsync(null);

        Assert.Empty(_client.BundleDownloads);
        Assert.Null(page.Message);
    }

    [Fact]
    public async Task A_failed_download_is_shown_and_its_file_removed()
    {
        _client.BundleError = FakeEngineClient.ApiError("session_still_active", "Still recording.");
        var page = Create();

        await page.ExportBundleCommand.ExecuteAsync(null);

        Assert.Equal("Still recording.", page.Error);
        Assert.Equal(1, _saver.Removed);
        Assert.Null(page.Message);
    }

    [Fact]
    public async Task An_unreachable_engine_is_named_when_exporting()
    {
        _client.BundleError = new EngineUnavailableException("refused", new HttpRequestException("refused"));
        var page = Create();

        await page.ExportBundleCommand.ExecuteAsync(null);

        Assert.Equal(_localization["EngineUnavailable"], page.Error);
    }

    [Fact]
    public void A_live_meeting_cannot_be_exported_as_a_recording()
    {
        Assert.False(Create("recording").ExportBundleCommand.CanExecute(null));
        Assert.True(Create().ExportBundleCommand.CanExecute(null));
    }

    [Fact]
    public async Task Deleting_the_audio_asks_first_then_removes_the_player()
    {
        var page = Create();
        await page.LoadAsync();
        Assert.True(page.HasAudio);
        var player = page.Player;

        await page.DeleteAudioCommand.ExecuteAsync(null);

        Assert.Equal(["Delete the audio?"], _dialogs.Asked);
        Assert.Contains("Weekly", _dialogs.Messages.Single());
        Assert.Equal([Id], _client.AudioDeleted);
        Assert.Null(page.Player);
        Assert.True(_player.Disposed);
        Assert.NotNull(player);
        Assert.False(page.HasAudio);
        Assert.False(page.OpenAudioCommand.CanExecute("mixed"));
        Assert.False(page.DeleteAudioCommand.CanExecute(null));
        Assert.Equal("Audio deleted. The transcript and minutes were kept.", page.Message);
    }

    [Fact]
    public async Task Cancelling_keeps_the_audio()
    {
        _dialogs.Answer = false;
        var page = Create();
        await page.LoadAsync();

        await page.DeleteAudioCommand.ExecuteAsync(null);

        Assert.Empty(_client.AudioDeleted);
        Assert.NotNull(page.Player);
    }

    [Fact]
    public async Task A_failed_delete_keeps_the_player_and_shows_the_error()
    {
        _client.DeleteAudioError = FakeEngineClient.ApiError("session_still_active", "Still recording.");
        var page = Create();
        await page.LoadAsync();

        await page.DeleteAudioCommand.ExecuteAsync(null);

        Assert.Equal("Still recording.", page.Error);
        Assert.NotNull(page.Player);
        Assert.True(page.HasAudio);
    }

    [Fact]
    public async Task Audio_can_only_be_deleted_when_there_is_some_and_the_meeting_is_over()
    {
        var page = Create();
        Assert.False(page.DeleteAudioCommand.CanExecute(null)); // not loaded yet

        await page.LoadAsync();
        Assert.True(page.DeleteAudioCommand.CanExecute(null));

        _client.Details[Id] = Detail(null);
        var silent = Create();
        await silent.LoadAsync();
        Assert.False(silent.DeleteAudioCommand.CanExecute(null));

        var live = Create("recording");
        await live.LoadAsync();
        Assert.False(live.DeleteAudioCommand.CanExecute(null));
    }
}
