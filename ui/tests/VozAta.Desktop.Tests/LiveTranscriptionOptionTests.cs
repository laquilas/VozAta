using System.Text.Json;
using VozAta.Client;
using VozAta.Desktop.Services;
using VozAta.Desktop.Tests.Fakes;
using VozAta.Desktop.ViewModels;

namespace VozAta.Desktop.Tests;

/// <summary>The "Live transcription" option of the recorder (phase 41): default, memory, notices.</summary>
public sealed class LiveTranscriptionOptionTests
{
    private readonly FakeEngineClient _client = new();
    private readonly FakePreferences _preferences = new();
    private readonly LocalizationService _localization = new();
    private readonly RecordingSessionService _session = new();

    private RecorderPageViewModel Create() =>
        new(_client, _localization, _preferences, new FakeClock(), new FakeTimer(),
            new MinutesTemplatesViewModel(_client), _session, _ => { })
        {
            IsEngineConnected = true,
        };

    private static EngineSettings SettingsWith(string? liveTranscription) =>
        new(
            liveTranscription is null
                ? new Dictionary<string, JsonElement>()
                : new Dictionary<string, JsonElement>
                {
                    ["LIVE_TRANSCRIPTION"] = JsonSerializer.SerializeToElement(bool.Parse(liveTranscription)),
                },
            []);

    [Theory]
    [InlineData(null, true)]
    [InlineData("true", true)]
    [InlineData("false", false)]
    public void Live_transcription_defaults_to_the_engine_setting(string? setting, bool expected)
    {
        var recorder = Create();

        recorder.ApplySettings(SettingsWith(setting));

        Assert.Equal(expected, recorder.LiveTranscription);
        Assert.Equal(0, _preferences.Saves); // applying a default is not a choice
    }

    [Fact]
    public void Remembered_choice_wins_and_is_saved()
    {
        var recorder = Create();
        recorder.ApplySettings(SettingsWith("true"));

        recorder.LiveTranscription = false;

        Assert.False(_preferences.Data.LiveTranscription);
        var next = Create();
        next.ApplySettings(SettingsWith("true"));
        Assert.False(next.LiveTranscription);
    }

    [Fact]
    public void Saving_the_setting_resets_the_choice()
    {
        var recorder = Create();
        recorder.ApplySettings(SettingsWith("true"));
        recorder.LiveTranscription = false;

        recorder.OnSettingsSaved(new Dictionary<string, string?> { ["LIVE_TRANSCRIPTION"] = "true" });

        Assert.True(recorder.LiveTranscription);
        Assert.Null(_preferences.Data.LiveTranscription);
    }

    [Fact]
    public async Task Saving_the_setting_while_recording_changes_nothing()
    {
        var recorder = Create();
        recorder.ApplySettings(SettingsWith("true"));
        await recorder.StartCommand.ExecuteAsync(null);

        recorder.OnSettingsSaved(new Dictionary<string, string?> { ["LIVE_TRANSCRIPTION"] = "false" });

        Assert.True(recorder.LiveTranscription);
    }

    [Fact]
    public async Task Start_sends_live_transcription()
    {
        var recorder = Create();
        recorder.ApplySettings(SettingsWith("true"));
        await recorder.StartCommand.ExecuteAsync(null);
        recorder.Handle(new StatusEvent(_session.SessionId, "done", 1));

        recorder.LiveTranscription = false;
        await recorder.StartCommand.ExecuteAsync(null);

        Assert.Equal([true, false], _client.StartRequests.Select(request => request.LiveTranscription));
    }

    [Fact]
    public void Unchecked_disables_translation_and_shows_the_audio_only_notice()
    {
        var recorder = Create();
        Assert.True(recorder.CanChooseTranslation);
        Assert.False(recorder.IsAudioOnlyNotice);

        recorder.LiveTranscription = false;

        Assert.False(recorder.CanChooseTranslation);
        Assert.True(recorder.IsAudioOnlyNotice);
        Assert.Equal("Recording audio only. The transcript is created after you stop.", recorder.L["TranscriptAudioOnly"]);
        recorder.Handle(new PartialEvent("s", "mic", "mic:1", "Me", 1, "hi"));
        Assert.False(recorder.IsAudioOnlyNotice); // text shown: no placeholder
    }

    [Fact]
    public async Task Option_is_read_only_while_recording()
    {
        var recorder = Create();
        await recorder.StartCommand.ExecuteAsync(null);

        recorder.LiveTranscription = false;

        Assert.True(recorder.LiveTranscription);
        Assert.False(recorder.CanEditOptions);
        Assert.Null(_preferences.Data.LiveTranscription);
    }
}
