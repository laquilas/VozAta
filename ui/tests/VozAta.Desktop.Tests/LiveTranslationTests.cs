using System.Text.Json;
using VozAta.Client;
using VozAta.Desktop.Services;
using VozAta.Desktop.Tests.Fakes;
using VozAta.Desktop.ViewModels;

namespace VozAta.Desktop.Tests;

/// <summary>Live translation (phase 29): the "Translate to" picker and translations under their lines.</summary>
public sealed class LiveTranslationTests
{
    private readonly FakeEngineClient _client = new();
    private readonly FakeEngineEvents _events = new();
    private readonly LocalizationService _localization = new();

    private async Task<MainViewModel> ReadyAsync()
    {
        var viewModel = new MainViewModel(
            _client, _events, new FakeEngineProcess(), new ImmediateDispatcher(), _localization, new FakeDialogs(),
            new FakePreferences(), new FakeClock(), new FakeTimer(), new FakeShell(), new FakeFileSaver(), new FakeThemeService());
        await viewModel.InitializeAsync();
        await SendAsync(viewModel, new ConnectionChangedEvent(true));
        return viewModel;
    }

    private async Task SendAsync(MainViewModel viewModel, EngineEvent engineEvent)
    {
        var before = viewModel.HandledEvents;
        _events.Send(engineEvent);
        for (var i = 0; i < 200 && viewModel.HandledEvents == before; i++)
        {
            await Task.Delay(5);
        }

        Assert.True(viewModel.HandledEvents > before, $"{engineEvent} was not handled");
    }

    private static SegmentEvent Segment(string id, string channel, double start, string text) =>
        new("s", new Segment(id, channel, channel, channel == "mic" ? "Me" : "Others", start, start + 1, text, false, []));

    [Fact]
    public async Task A_translation_is_shown_under_the_line_of_its_segment()
    {
        var viewModel = await ReadyAsync();
        await SendAsync(viewModel, Segment("mic-000001", "mic", 1, "Good morning."));
        await SendAsync(viewModel, Segment("system-000001", "system", 2, "Hi there."));

        await SendAsync(viewModel, new TranslationEvent("s", "system-000001", "pt", "Olá."));
        await SendAsync(viewModel, new TranslationEvent("s", "mic-999999", "pt", "unknown line"));

        Assert.Null(viewModel.Recorder.Segments[0].Translation);
        Assert.False(viewModel.Recorder.Segments[0].HasTranslation);
        Assert.Equal("Olá.", viewModel.Recorder.Segments[1].Translation);
        Assert.True(viewModel.Recorder.Segments[1].HasTranslation);
        Assert.Equal("[00:00:02] Others: Hi there.", viewModel.Recorder.Segments[1].Display);
    }

    [Fact]
    public async Task Relabeled_live_lines_keep_their_translations()
    {
        var viewModel = await ReadyAsync();
        await SendAsync(viewModel, Segment("system-000001", "system", 1, "Hi."));
        await SendAsync(viewModel, new TranslationEvent("s", "system-000001", "pt", "Oi."));
        _client.Transcripts["s"] = new Transcript(
            "diarized",
            [new Segment("system-000001", "system", "system:1", "User 1", 1, 2, "Hi.", false, [], new SegmentTranslation("pt", "Oi."))]);

        await SendAsync(viewModel, new SpeakersRelabeledEvent("s"));
        await viewModel.HistoryRefresh;

        Assert.Equal("User 1", viewModel.Recorder.Segments.Single().Label);
        Assert.Equal("Oi.", viewModel.Recorder.Segments.Single().Translation);
        await SendAsync(viewModel, new TranslationEvent("s", "system-000001", "pt", "Olá."));
        Assert.Equal("Olá.", viewModel.Recorder.Segments.Single().Translation); // the line index was rebuilt
    }

    [Fact]
    public async Task A_new_recording_forgets_the_lines_of_the_previous_one()
    {
        var viewModel = await ReadyAsync();
        await SendAsync(viewModel, Segment("mic-000001", "mic", 1, "Old."));

        await viewModel.Recorder.StartCommand.ExecuteAsync(null);
        await SendAsync(viewModel, new TranslationEvent("s", "mic-000001", "pt", "Velho."));

        Assert.Empty(viewModel.Recorder.Segments);
    }

    [Fact]
    public async Task The_picker_starts_from_translate_to_and_only_a_different_choice_is_sent()
    {
        _client.SettingValues["TRANSLATE_TO"] = "pt";
        var viewModel = await ReadyAsync();

        Assert.Equal("pt", viewModel.Recorder.SelectedTranslation.Value);
        Assert.Equal(["Off", "English", "Portuguese", "Spanish"], viewModel.Recorder.TranslationLanguages.Select(o => o.Label));
        await viewModel.Recorder.StartCommand.ExecuteAsync(null);
        Assert.Null(_client.StartRequests.Single().TranslateTo); // the engine applies TRANSLATE_TO

        await SendAsync(viewModel, new StatusEvent("s", "done", 3));
        viewModel.Recorder.SelectedTranslation = viewModel.Recorder.TranslationLanguages[0];
        await viewModel.Recorder.StartCommand.ExecuteAsync(null);
        Assert.Equal("off", _client.StartRequests[1].TranslateTo);
    }

    [Fact]
    public async Task Without_a_setting_translation_is_off_and_labels_follow_the_ui_language()
    {
        var viewModel = await ReadyAsync();

        Assert.Equal("off", viewModel.Recorder.SelectedTranslation.Value);
        _localization.SetLanguage("pt-BR");
        Assert.Equal("Desligado", viewModel.Recorder.TranslationLanguages[0].Label);
    }

    [Fact]
    public async Task A_saved_translate_to_becomes_the_new_default()
    {
        _client.Schema.Add(new SettingSchema(
            "TRANSLATE_TO", "choice", JsonSerializer.SerializeToElement("off"), ["off", "en", "pt", "es"], false, "transcription"));
        var viewModel = await ReadyAsync();
        var editor = viewModel.Settings.Groups.Single().Editors.Single();
        Assert.Equal("Off", editor.Choices[0].Label);
        editor.SelectedChoice = editor.Choices.Single(choice => choice.Value == "es");

        await viewModel.Settings.SaveCommand.ExecuteAsync(null);

        Assert.Equal("es", viewModel.Recorder.SelectedTranslation.Value);
    }
}
