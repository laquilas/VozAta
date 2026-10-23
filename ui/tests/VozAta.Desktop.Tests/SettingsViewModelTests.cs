using System.Text.Json;
using VozAta.Client;
using VozAta.Desktop.Services;
using VozAta.Desktop.Tests.Fakes;
using VozAta.Desktop.ViewModels;

namespace VozAta.Desktop.Tests;

public sealed class SettingsViewModelTests
{
    private readonly FakeEngineClient _client = new();
    private readonly FakeEngineProcess _process = new();
    private readonly LocalizationService _localization = new();

    public SettingsViewModelTests()
    {
        Add("APP_LANGUAGE", "choice", "en", "general", choices: ["en", "pt-BR", "es"]);
        Add("MIC_LABEL", "string", null, "general");
        Add("GENERATE_MINUTES", "bool", true, "general");
        Add("MIX_MODE", "choice", "mono", "audio", choices: ["mono", "stereo"]);
        Add("CHUNK_SECONDS", "number", 5.0, "segmentation");
        Add("VAD_MIN_SILENCE_MS", "integer", 600, "segmentation");
        Add("WHISPER_MODEL", "string", "large-v3-turbo", "transcription", applies: "restart");
        Add("OLLAMA_URL", "url", "http://localhost:11434", "minutes");
        Add("HF_TOKEN", "string", "", "speakers", secret: true);
        _client.SettingValues["MIC_LABEL"] = null;
        _client.SettingValues["HF_TOKEN"] = "********";
        _client.RestartKeys.Add("WHISPER_MODEL");
    }

    private void Add(string key, string type, object? value, string group, string[]? choices = null, string applies = "next_session", bool secret = false)
    {
        _client.Schema.Add(new SettingSchema(key, type, JsonSerializer.SerializeToElement(value), choices, secret, group, applies));
        _client.SettingValues[key] = value;
    }

    private async Task<SettingsViewModel> LoadedAsync()
    {
        var settings = new SettingsViewModel(_client, _process, _localization);
        await settings.LoadAsync();
        return settings;
    }

    private static SettingEditorViewModel Editor(SettingsViewModel settings, string key) =>
        settings.Groups.SelectMany(group => group.Editors).Single(editor => editor.Key == key);

    [Fact]
    public async Task Minutes_template_choices_show_the_template_names()
    {
        Add("MINUTES_TEMPLATE", "choice", "general", "minutes", choices: ["general", "daily", "one_on_one", "client", "retrospective"]);

        var settings = await LoadedAsync();

        Assert.Equal(
            ["General meeting", "Daily stand-up", "One-on-one", "Client meeting", "Retrospective"],
            Editor(settings, "MINUTES_TEMPLATE").Choices.Select(choice => choice.Label));
    }

    [Fact]
    public async Task Editors_are_grouped_in_page_order_with_a_kind_per_type()
    {
        var settings = await LoadedAsync();

        Assert.Equal(["general", "audio", "segmentation", "transcription", "speakers", "minutes"], settings.Groups.Select(group => group.Id));
        Assert.Equal(_localization["SettingsGroup_general"], settings.Groups[0].Title);
        Assert.Equal(
            [
                ("APP_LANGUAGE", SettingKind.Choice), ("MIC_LABEL", SettingKind.Text), ("GENERATE_MINUTES", SettingKind.Toggle),
                ("MIX_MODE", SettingKind.Choice), ("CHUNK_SECONDS", SettingKind.Number), ("VAD_MIN_SILENCE_MS", SettingKind.WholeNumber),
                ("WHISPER_MODEL", SettingKind.Text), ("HF_TOKEN", SettingKind.Secret), ("OLLAMA_URL", SettingKind.Url),
            ],
            settings.Groups.SelectMany(group => group.Editors).Select(editor => (editor.Key, editor.Kind)));
        var chunk = Editor(settings, "CHUNK_SECONDS");
        Assert.Equal((5.0m, _localization["Setting_CHUNK_SECONDS"], _localization["SettingHelp_CHUNK_SECONDS"]), (chunk.NumberValue, chunk.Label, chunk.Help));
        Assert.True(Editor(settings, "WHISPER_MODEL").NeedsRestart);
        Assert.Equal(["English", "Português (Brasil)", "Español"], Editor(settings, "APP_LANGUAGE").Choices.Select(choice => choice.Label));
        Assert.Equal("mono", Editor(settings, "MIX_MODE").SelectedChoice!.Value);
        Assert.True(Editor(settings, "GENERATE_MINUTES").BoolValue);
        Assert.Equal("", Editor(settings, "MIC_LABEL").TextValue);
        Assert.False(settings.IsDirty);
        Assert.False(settings.SaveCommand.CanExecute(null));
    }

    [Fact]
    public async Task Changes_are_dirty_and_save_sends_only_them_as_json_values()
    {
        var settings = await LoadedAsync();

        Editor(settings, "CHUNK_SECONDS").NumberValue = 8m;
        Editor(settings, "VAD_MIN_SILENCE_MS").NumberValue = 800m;
        Editor(settings, "GENERATE_MINUTES").BoolValue = false;
        var mix = Editor(settings, "MIX_MODE");
        mix.SelectedChoice = mix.Choices.Single(choice => choice.Value == "stereo");
        Editor(settings, "MIC_LABEL").TextValue = "Host";
        Assert.True(settings.IsDirty);
        Assert.True(Editor(settings, "CHUNK_SECONDS").IsDirty);
        Assert.False(Editor(settings, "OLLAMA_URL").IsDirty);

        await settings.SaveCommand.ExecuteAsync(null);

        var sent = _client.Updates.Single();
        Assert.Equal(
            new HashSet<string> { "CHUNK_SECONDS", "VAD_MIN_SILENCE_MS", "GENERATE_MINUTES", "MIX_MODE", "MIC_LABEL" },
            sent.Keys.ToHashSet());
        Assert.Equal((8.0, 800, false, "stereo", "Host"), ((double)sent["CHUNK_SECONDS"]!, (int)sent["VAD_MIN_SILENCE_MS"]!, (bool)sent["GENERATE_MINUTES"]!, (string)sent["MIX_MODE"]!, (string)sent["MIC_LABEL"]!));
        Assert.False(settings.IsDirty);
        Assert.Equal(_localization["SettingsSaved"], settings.Message);
        Assert.Empty(settings.RestartKeys);
    }

    [Fact]
    public async Task Clearing_text_sends_null_and_an_untouched_secret_is_never_sent()
    {
        _client.SettingValues["MIC_LABEL"] = "Host";
        var settings = await LoadedAsync();

        Editor(settings, "MIC_LABEL").TextValue = "  ";
        await settings.SaveCommand.ExecuteAsync(null);

        var sent = _client.Updates.Single();
        Assert.Equal(["MIC_LABEL"], sent.Keys);
        Assert.Null(sent["MIC_LABEL"]);
        Assert.Equal("", Editor(settings, "HF_TOKEN").TextValue); // the mask never reaches the box
        Assert.True(Editor(settings, "HF_TOKEN").HasStoredSecret);
    }

    [Fact]
    public async Task Discard_restores_the_loaded_values()
    {
        var settings = await LoadedAsync();
        Editor(settings, "CHUNK_SECONDS").NumberValue = 9m;

        settings.DiscardCommand.Execute(null);

        Assert.Equal(5.0m, Editor(settings, "CHUNK_SECONDS").NumberValue);
        Assert.False(settings.IsDirty);
        Assert.Empty(_client.Updates);
    }

    [Fact]
    public async Task An_invalid_value_is_shown_on_its_editor_and_stays_dirty()
    {
        var settings = await LoadedAsync();
        _client.UpdateError = new EngineApiException(System.Net.HttpStatusCode.UnprocessableEntity, "invalid_setting", "Must be between 1 and 60.", "CHUNK_SECONDS");
        var chunk = Editor(settings, "CHUNK_SECONDS");
        chunk.NumberValue = 500m;

        await settings.SaveCommand.ExecuteAsync(null);

        Assert.Equal("Must be between 1 and 60.", chunk.Error);
        Assert.True(settings.IsDirty);
        Assert.Null(settings.Message);
        _client.UpdateError = null;
        chunk.NumberValue = 8m;
        Assert.Null(chunk.Error);  // editing clears the error
    }

    [Fact]
    public async Task Other_save_errors_are_shown_on_the_page()
    {
        var settings = await LoadedAsync();
        _client.UpdateError = new EngineUnavailableException("refused", new HttpRequestException());
        Editor(settings, "CHUNK_SECONDS").NumberValue = 8m;

        await settings.SaveCommand.ExecuteAsync(null);

        Assert.Equal(_localization["EngineUnavailable"], settings.Error);
    }

    [Fact]
    public async Task Restart_keys_prompt_and_restart_the_engine()
    {
        var settings = await LoadedAsync();
        Editor(settings, "WHISPER_MODEL").TextValue = "medium";

        await settings.SaveCommand.ExecuteAsync(null);
        Assert.Equal([_localization["Setting_WHISPER_MODEL"]], settings.RestartKeys);
        Assert.True(settings.RestartEngineCommand.CanExecute(null));

        await settings.RestartEngineCommand.ExecuteAsync(null);

        Assert.Equal(1, _process.Restarts);
        Assert.Empty(settings.RestartKeys);
        Assert.Equal(_localization["EngineRestarted"], settings.Message);
    }

    [Theory]
    [InlineData(EngineRestartResult.NotOwned, "EngineRestartManual")]
    [InlineData(EngineRestartResult.Failed, "EngineRestartFailed")]
    public async Task A_restart_the_app_cannot_do_is_explained(EngineRestartResult result, string messageKey)
    {
        _process.RestartResult = result;
        var settings = await LoadedAsync();
        Editor(settings, "WHISPER_MODEL").TextValue = "medium";
        await settings.SaveCommand.ExecuteAsync(null);

        await settings.RestartEngineCommand.ExecuteAsync(null);

        Assert.Equal(_localization[messageKey], result == EngineRestartResult.Failed ? settings.Error : settings.Message);
        Assert.NotEmpty(settings.RestartKeys);
    }

    [Fact]
    public async Task Saved_values_are_reported_to_listeners()
    {
        var settings = await LoadedAsync();
        IReadOnlyDictionary<string, string?>? saved = null;
        settings.Saved += values => saved = values;
        var language = Editor(settings, "APP_LANGUAGE");

        language.SelectedChoice = language.Choices.Single(choice => choice.Value == "pt-BR");
        await settings.SaveCommand.ExecuteAsync(null);

        Assert.Equal("pt-BR", saved!["APP_LANGUAGE"]);
    }

    [Fact]
    public async Task A_single_value_saved_elsewhere_updates_its_editor()
    {
        var settings = await LoadedAsync();

        await settings.SaveValueAsync("APP_LANGUAGE", "es");

        Assert.Equal("es", Editor(settings, "APP_LANGUAGE").SelectedChoice!.Value);
        Assert.False(settings.IsDirty);
        Assert.Equal("es", (string)_client.Updates.Single()["APP_LANGUAGE"]!);
    }

    [Fact]
    public async Task Labels_follow_the_ui_language()
    {
        var settings = await LoadedAsync();

        _localization.SetLanguage("es");
        settings.RefreshTexts();

        Assert.Equal(_localization["Setting_CHUNK_SECONDS"], Editor(settings, "CHUNK_SECONDS").Label);
        Assert.Equal(_localization["SettingsGroup_audio"], settings.Groups[1].Title);
    }

    [Fact]
    public async Task A_load_failure_is_shown()
    {
        _client.SettingsError = new EngineUnavailableException("refused", new HttpRequestException());

        var settings = await LoadedAsync();

        Assert.Equal(_localization["EngineUnavailable"], settings.Error);
        Assert.Empty(settings.Groups);
    }

    [Fact]
    public async Task Options_read_well_for_screen_readers()
    {
        var settings = await LoadedAsync();
        var main = new ChoiceOption("pt", "LanguagePt");
        main.Refresh(_localization);

        Assert.Equal("Português (Brasil)", Editor(settings, "APP_LANGUAGE").Choices[1].ToString());
        Assert.Equal("stereo", Editor(settings, "MIX_MODE").Choices[1].ToString());
        Assert.Equal("Portuguese", main.ToString());
    }

    [Fact]
    public async Task The_worker_switches_set_the_provider_keys()
    {
        Add("STT_PROVIDER", "string", "openai_compatible", "transcription", applies: "restart");
        Add("DIARIZATION_PROVIDER", "string", "vozata_worker", "speakers");
        Add("TRANSLATION_PROVIDER", "string", "opus_mt", "transcription");
        Add("WORKER_URL", "url", "http://192.168.0.30:8766", "worker");
        var settings = await LoadedAsync();
        var tasks = settings.Groups.Single(group => group.Id == "worker").Tasks!;
        Assert.Null(settings.Groups.Single(group => group.Id == "general").Tasks);
        Assert.Equal((false, true, false), (tasks.UseForSpeech, tasks.UseForSpeakers, tasks.UseForTranslation));

        tasks.UseForSpeech = true;
        tasks.UseForTranslation = true;
        tasks.UseForSpeakers = true; // already on: unchanged

        Assert.Equal("vozata_worker", Editor(settings, "STT_PROVIDER").TextValue);
        Assert.Equal("vozata_worker", Editor(settings, "TRANSLATION_PROVIDER").TextValue);
        Assert.False(Editor(settings, "DIARIZATION_PROVIDER").IsDirty);
        Assert.True(settings.IsDirty);

        tasks.UseForSpeech = false; // back to the provider it had
        Assert.Equal("openai_compatible", Editor(settings, "STT_PROVIDER").TextValue);
    }

    [Fact]
    public async Task Switching_the_worker_off_goes_back_to_the_default_provider_and_follows_edits()
    {
        _client.Schema.Add(new SettingSchema("DIARIZATION_PROVIDER", "string", JsonSerializer.SerializeToElement("pyannote"), null, false, "speakers"));
        _client.SettingValues["DIARIZATION_PROVIDER"] = "vozata_worker";
        Add("WORKER_URL", "url", "http://192.168.0.30:8766", "worker");
        var settings = await LoadedAsync();
        var tasks = settings.Groups.Single(group => group.Id == "worker").Tasks!;
        var changed = new List<string?>();
        tasks.PropertyChanged += (_, args) => changed.Add(args.PropertyName);

        tasks.UseForSpeakers = false;
        Assert.Equal("pyannote", Editor(settings, "DIARIZATION_PROVIDER").TextValue);

        Editor(settings, "DIARIZATION_PROVIDER").TextValue = "vozata_worker"; // typed in its own group
        Assert.True(tasks.UseForSpeakers);
        Assert.Contains(nameof(WorkerTasksViewModel.UseForSpeakers), changed);
        Assert.False(tasks.HasSpeech); // no such key: the switch is hidden
        tasks.UseForSpeech = true; // and does nothing
        Assert.False(tasks.UseForSpeech);
    }
}
