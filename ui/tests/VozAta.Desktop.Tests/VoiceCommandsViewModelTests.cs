using System.Net;
using System.Text.Json;
using VozAta.Client;
using VozAta.Desktop.Services;
using VozAta.Desktop.Tests.Fakes;
using VozAta.Desktop.ViewModels;

namespace VozAta.Desktop.Tests;

/// <summary>Voice commands on the Config page and in the recorder (phase 50).</summary>
public sealed class VoiceCommandsViewModelTests
{
    private const string SessionId = "20261016_090000";

    private readonly FakeEngineClient _client = new();
    private readonly LocalizationService _localization = new();
    private readonly FakeShell _shell = new();
    private readonly List<string> _notified = [];

    [Fact]
    public async Task The_list_loads_edits_and_saves_trimmed()
    {
        var commands = new VoiceCommandsViewModel(_client, _localization);
        await commands.LoadAsync();
        Assert.Equal(["make the minutes", "what was decided"], commands.Rows.Select(row => row.Phrase));
        Assert.False(commands.Rows[0].IsAsk);
        Assert.True(commands.Rows[1].IsAsk);
        Assert.Equal(_localization["VoiceActionMinutes"], commands.Rows[0].Action.Label);

        commands.AddCommand.Execute(null);
        var added = commands.Rows[2];
        added.Phrase = "  next steps ";
        added.Question = " What are the next steps? ";
        commands.Rows[0].Action = commands.Actions[1]; // now a question
        commands.Rows[0].Question = "Summary?";
        commands.RemoveCommand.Execute(commands.Rows[1]);
        await commands.SaveCommand.ExecuteAsync(null);

        Assert.Equal(
            [new VoiceCommand("make the minutes", "ask", "Summary?"), new VoiceCommand("next steps", "ask", "What are the next steps?")],
            _client.SavedVoiceCommands);
        Assert.Equal(_localization["VoiceCommandsSaved"], commands.Message);
    }

    [Fact]
    public async Task A_minutes_command_keeps_no_question_and_defaults_come_back()
    {
        _client.SavedVoiceCommands = [new VoiceCommand("recap", "minutes", null)];
        var commands = new VoiceCommandsViewModel(_client, _localization);
        await commands.LoadAsync();
        commands.Rows[0].Question = "ignored";

        Assert.Null(commands.Rows[0].ToCommand().Question);
        commands.RestoreDefaultsCommand.Execute(null);

        Assert.Equal(["make the minutes", "what was decided"], commands.Rows.Select(row => row.Phrase));
        Assert.Equal(_localization["VoiceCommandsDefaultsRestored"], commands.Message);
    }

    [Fact]
    public async Task A_refused_list_shows_the_engine_message()
    {
        var commands = new VoiceCommandsViewModel(_client, _localization);
        await commands.LoadAsync();
        _client.VoiceCommandsError = new EngineApiException(
            HttpStatusCode.UnprocessableEntity, "invalid_voice_commands", "Command 1 needs a question.");

        await commands.SaveCommand.ExecuteAsync(null);
        await commands.LoadAsync();

        Assert.Equal("Command 1 needs a question.", commands.Error);
        Assert.False(commands.IsBusy);
    }

    [Fact]
    public async Task The_voice_group_of_the_config_page_has_the_list()
    {
        _client.Schema.Add(new SettingSchema("WAKE_WORD", "string", JsonSerializer.SerializeToElement("VozAta"), null, false, "voice", "next_session", null));
        _client.Schema.Add(new SettingSchema("MIX_MODE", "choice", JsonSerializer.SerializeToElement("mono"), ["mono", "stereo"], false, "audio", "next_session", null));
        var settings = new SettingsViewModel(_client, new FakeEngineProcess(), _localization);

        await settings.LoadAsync();

        var voice = settings.Groups.Single(group => group.Id == "voice");
        Assert.True(voice.HasCommands);
        Assert.Equal(2, voice.Commands!.Rows.Count);
        Assert.False(settings.Groups.Single(group => group.Id == "audio").HasCommands);
    }

    private RecorderPageViewModel Recorder() =>
        new(_client, _localization, new FakePreferences(), new FakeClock(), new FakeTimer(),
            new MinutesTemplatesViewModel(_client), new RecordingSessionService(), _notified.Add, shell: _shell)
        {
            IsEngineConnected = true,
        };

    [Fact]
    public async Task A_question_by_voice_streams_into_the_recorder()
    {
        var recorder = Recorder();
        await recorder.StartCommand.ExecuteAsync(null);

        recorder.OnVoiceCommand(new VoiceCommandEvent("other", "ask", "x", "?", "voice-0"));
        Assert.False(recorder.VoiceAnswer.IsOpen);
        recorder.OnVoiceCommand(new VoiceCommandEvent(SessionId, "ask", "o que foi decidido", "O que foi decidido?", "voice-1"));
        recorder.VoiceAnswer.OnChunk(new AnswerChunkEvent(SessionId, "voice-1", "Beta "));
        recorder.VoiceAnswer.OnChunk(new AnswerChunkEvent(SessionId, "a-typed-question", "no"));
        recorder.VoiceAnswer.OnChunk(new AnswerChunkEvent(SessionId, "voice-1", "na terça."));

        var answer = recorder.VoiceAnswer;
        Assert.True(answer.IsOpen && answer.IsAnswering);
        Assert.Equal(("O que foi decidido?", "Beta na terça."), (answer.Question, answer.Text));
        answer.OnDone(new AnswerDoneEvent(SessionId, "other", [], "x"));
        answer.OnDone(new AnswerDoneEvent(SessionId, "voice-1", [], null));
        Assert.False(answer.IsAnswering);

        await answer.CopyCommand.ExecuteAsync(null);
        answer.CloseCommand.Execute(null);

        Assert.Equal(["O que foi decidido?\n\nBeta na terça."], _shell.Copied);
        Assert.False(answer.IsOpen);
    }

    [Fact]
    public async Task Minutes_by_voice_open_like_a_click()
    {
        var recorder = Recorder();
        await recorder.StartCommand.ExecuteAsync(null);

        recorder.OnVoiceCommand(new VoiceCommandEvent(SessionId, "minutes", "gere a ata", null, null));
        Assert.True(recorder.MinutesSoFar.IsWriting);
        _client.PartialMinutes[SessionId] = [new PartialMinutesDetail("p1", "t", 0, 60, "voice", null, "# Ata\n")];
        await recorder.MinutesSoFar.OnReadyAsync(new PartialMinutesReadyEvent(SessionId, "p1", 0, 60, "voice"));

        Assert.True(recorder.MinutesSoFar.IsOpen);
        Assert.Empty(_client.PartialRequests); // the engine started them itself
    }

    [Fact]
    public async Task A_failed_answer_shows_its_error()
    {
        var answer = new VoiceAnswerViewModel(null, _localization, _notified.Add);
        answer.Begin("voice-1", null);

        answer.OnDone(new AnswerDoneEvent(SessionId, "voice-1", [], "Ollama is off."));
        await answer.CopyCommand.ExecuteAsync(null); // no clipboard: nothing happens

        Assert.Equal("Ollama is off.", answer.Error);
        Assert.Empty(_notified);
    }

    [Fact]
    public void The_voice_command_event_is_parsed() =>
        Assert.Equal(
            new VoiceCommandEvent("s1", "ask", "o que foi decidido", "O que foi decidido?", "voice-1"),
            EngineEventParser.Parse("""
                {"type": "voice_command", "session_id": "s1",
                 "data": {"action": "ask", "phrase": "o que foi decidido", "question": "O que foi decidido?", "answer_id": "voice-1"}}
                """));
}
