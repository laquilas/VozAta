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
    public async Task Unchecked_disables_translation_and_shows_the_audio_only_notice_while_recording()
    {
        var recorder = Create();
        Assert.True(recorder.CanChooseTranslation);

        recorder.LiveTranscription = false;

        Assert.False(recorder.CanChooseTranslation);
        Assert.False(recorder.IsAudioOnlyNotice); // idle: the usual "Press Start..." prompt
        Assert.True(recorder.IsStartPromptVisible);
        await recorder.StartCommand.ExecuteAsync(null);
        Assert.True(recorder.IsAudioOnlyNotice);
        Assert.False(recorder.IsStartPromptVisible);
        Assert.Equal("Recording audio only. The transcript is created after you stop.", recorder.L["TranscriptAudioOnly"]);
        recorder.Handle(new StatusEvent(_session.SessionId, "paused", 1));
        Assert.True(recorder.IsAudioOnlyNotice);
        recorder.Handle(new PartialEvent("s", "mic", "mic:1", "Me", 1, "hi"));
        Assert.False(recorder.IsAudioOnlyNotice); // text shown: no placeholder
        Assert.False(recorder.IsStartPromptVisible);
    }

    [Fact]
    public async Task The_audio_only_notice_ends_with_the_recording()
    {
        var recorder = Create();
        recorder.LiveTranscription = false;
        await recorder.StartCommand.ExecuteAsync(null);

        recorder.Handle(new StatusEvent(_session.SessionId, "finalizing", 2));

        Assert.False(recorder.IsAudioOnlyNotice);
        Assert.True(recorder.IsStartPromptVisible);
    }

    [Fact]
    public async Task A_live_recording_shows_the_start_prompt_until_text_arrives()
    {
        var recorder = Create();

        await recorder.StartCommand.ExecuteAsync(null);

        Assert.False(recorder.IsAudioOnlyNotice);
        Assert.True(recorder.IsStartPromptVisible);
    }

    [Theory]
    [InlineData(false, true)]
    [InlineData(true, false)]
    [InlineData(null, false)]
    public async Task An_adopted_recording_shows_its_own_mode(bool? stored, bool notice)
    {
        const string id = "20261020_100000";
        _client.Details[id] = new SessionDetail(id, "recording", null, null, 1, "en", false, [], "folder")
        {
            Metadata = stored is { } live
                ? new Dictionary<string, JsonElement> { ["live_transcription"] = JsonSerializer.SerializeToElement(live) }
                : null,
        };
        var recorder = Create(); // the chip stays as the user left it (checked)

        recorder.Handle(new StatusEvent(id, "recording", 5));
        await recorder.RecordingModeLookup;

        Assert.Equal(notice, recorder.IsAudioOnlyNotice);
        Assert.True(recorder.LiveTranscription);
        Assert.Null(_preferences.Data.LiveTranscription);
    }

    [Fact]
    public async Task An_adopted_recording_whose_detail_fails_counts_as_live()
    {
        var recorder = Create();
        recorder.LiveTranscription = false; // the chip does not decide for a recording started elsewhere

        recorder.Handle(new StatusEvent("20261020_100000", "recording", 5)); // unknown: 404
        await recorder.RecordingModeLookup;

        Assert.False(recorder.IsAudioOnlyNotice);
        Assert.False(recorder.LiveTranscription);
    }

    [Fact]
    public async Task A_recording_this_page_started_is_not_looked_up()
    {
        var recorder = Create();
        recorder.LiveTranscription = false;
        _client.DetailError = new InvalidOperationException("must not be read");

        await recorder.StartCommand.ExecuteAsync(null);
        recorder.Handle(new StatusEvent(_session.SessionId, "recording", 1));

        Assert.True(recorder.RecordingModeLookup.IsCompletedSuccessfully); // never read: the fake would throw
        Assert.True(recorder.IsAudioOnlyNotice);
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
