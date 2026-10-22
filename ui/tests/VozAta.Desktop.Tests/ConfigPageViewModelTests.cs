using System.Text.Json;
using VozAta.Client;
using VozAta.Desktop.Services;
using VozAta.Desktop.Tests.Fakes;
using VozAta.Desktop.ViewModels;

namespace VozAta.Desktop.Tests;

public sealed class ConfigPageViewModelTests
{
    private readonly FakeEngineClient _client = new();
    private readonly FakeShell _shell = new();
    private readonly FakeDialogs _dialogs = new();
    private readonly LocalizationService _localization = new();

    public ConfigPageViewModelTests()
    {
        Add("APP_LANGUAGE", "choice", "en", "general", choices: ["en", "pt-BR", "es"]);
        Add("OUTPUT_DIR", "path", "recordings", "general", applies: "restart");
        Add("MIX_MODE", "choice", "mono", "audio", choices: ["mono", "stereo"]);
        Add("WHISPER_MODEL", "string", "large-v3-turbo", "transcription", applies: "restart", source: "whisper_models");
        Add("OPENAI_STT_URL", "url", "https://api.openai.com/v1", "transcription");
        Add("HF_TOKEN", "string", "********", "speakers", secret: true);
        Add("OLLAMA_URL", "url", "http://localhost:11434", "minutes");
        Add("OLLAMA_MODEL", "string", "qwen2.5:7b", "minutes", source: "ollama_models");
        Add("AZDO_PAT", "string", null, "tasks", secret: true);
        Add("GITHUB_TOKEN", "string", null, "tasks", secret: true);
        _client.Health = _client.Health with
        {
            Storage = new StorageStatus("sqlite", @"C:\data\vozata.db", null, 5 * 1024 * 1024, 1536),
        };
        _client.Options = new SettingOptions(
            new Dictionary<string, IReadOnlyList<SettingOption>>
            {
                ["whisper_models"] = [new("large-v3-turbo", "large-v3-turbo"), new("small", "small", false)],
                ["ollama_models"] = [],
            },
            new Dictionary<string, bool> { ["ollama_models"] = false });
    }

    private void Add(
        string key, string type, object? value, string group, string[]? choices = null, string applies = "next_session",
        bool secret = false, string? source = null)
    {
        _client.Schema.Add(new SettingSchema(key, type, JsonSerializer.SerializeToElement(value), choices, secret, group, applies, source));
        _client.SettingValues[key] = value;
    }

    private ConfigPageViewModel Page(IPathPicker? paths = null)
    {
        var health = new HealthViewModel(_client, _localization);
        return new ConfigPageViewModel(
            new SettingsViewModel(_client, new FakeEngineProcess(), _localization, paths),
            new StorageViewModel(_client, _shell, _dialogs, _localization),
            new AboutViewModel(health, _shell),
            _localization);
    }

    private async Task<ConfigPageViewModel> LoadedAsync(IPathPicker? paths = null)
    {
        var page = Page(paths);
        await page.LoadAsync();
        return page;
    }

    private static SettingEditorViewModel Editor(ConfigPageViewModel page, string key) =>
        page.Settings.Editors.Single(editor => editor.Key == key);

    [Fact]
    public async Task Sections_are_the_engine_groups_then_the_app_sections()
    {
        var page = await LoadedAsync();

        Assert.Equal(
            ["general", "audio", "transcription", "speakers", "minutes", "tasks", "desktop", "vocabulary", "storage", "about"],
            page.Sections.Select(section => section.Id));
        Assert.Equal(_localization["SettingsGroup_general"], page.Sections[0].Title);
        Assert.Equal(_localization["ConfigSection_storage"], page.Sections[8].ToString());
        Assert.Same(page.Sections[0], page.SelectedSection);
        Assert.Equal(["general"], page.VisibleGroups.Select(group => group.Id));
        Assert.False(page.ShowDesktop || page.ShowVocabulary || page.ShowStorage || page.ShowAbout);
    }

    [Fact]
    public void Before_loading_only_the_app_sections_exist()
    {
        var page = Page();

        Assert.Equal(["desktop", "vocabulary", "storage", "about"], page.Sections.Select(section => section.Id));
        Assert.True(page.ShowDesktop);
    }

    [Fact]
    public async Task Selecting_a_section_shows_only_its_cards()
    {
        var page = await LoadedAsync();

        page.Select("minutes");
        Assert.Equal(["minutes"], page.VisibleGroups.Select(group => group.Id));

        page.Select("storage");
        Assert.Empty(page.VisibleGroups);
        Assert.True(page.ShowStorage);
        Assert.False(page.ShowAbout);

        page.Select("nowhere");
        Assert.True(page.ShowStorage);
    }

    [Theory]
    [InlineData("desktop")]
    [InlineData("vocabulary")]
    [InlineData("about")]
    public async Task Each_app_section_shows_its_card(string id)
    {
        var page = await LoadedAsync();

        page.Select(id);

        Assert.Equal(
            (id == "desktop", id == "vocabulary", id == "about"),
            (page.ShowDesktop, page.ShowVocabulary, page.ShowAbout));
    }

    [Fact]
    public async Task Search_filters_keys_across_sections()
    {
        var page = await LoadedAsync();

        page.SearchText = "_model"; // key names: WHISPER_MODEL and OLLAMA_MODEL

        Assert.True(page.IsSearching);
        Assert.Equal(["transcription", "minutes"], page.VisibleGroups.Select(group => group.Id));
        Assert.True(Editor(page, "WHISPER_MODEL").IsVisible);
        Assert.False(Editor(page, "OPENAI_STT_URL").IsVisible);
        Assert.True(Editor(page, "OLLAMA_MODEL").IsVisible);
        Assert.False(Editor(page, "OLLAMA_URL").IsVisible);
        Assert.Equal(
            ["transcription", "minutes"],
            page.Sections.Where(section => section.IsVisible).Select(section => section.Id));
        Assert.False(page.HasNoResults);
    }

    [Fact]
    public async Task Search_matches_key_names_and_app_section_titles()
    {
        var page = await LoadedAsync();

        page.SearchText = "hf_token";
        Assert.Equal(["speakers"], page.VisibleGroups.Select(group => group.Id));

        page.SearchText = _localization["ConfigSection_storage"];
        Assert.True(page.ShowStorage);
        Assert.False(page.ShowAbout);
    }

    [Fact]
    public async Task A_search_without_matches_says_so_and_clearing_restores_the_section()
    {
        var page = await LoadedAsync();
        page.Select("audio");

        page.SearchText = "zzz-nothing";
        Assert.True(page.HasNoResults);
        Assert.Empty(page.VisibleGroups);

        page.SearchText = "";
        Assert.False(page.HasNoResults);
        Assert.Equal(["audio"], page.VisibleGroups.Select(group => group.Id));
        Assert.All(page.Settings.Editors, editor => Assert.True(editor.IsVisible));
    }

    [Fact]
    public async Task Picking_a_section_leaves_the_search()
    {
        var page = await LoadedAsync();
        page.SearchText = "model";

        page.SelectedSection = page.Sections.Single(section => section.Id == "tasks");

        Assert.Equal("", page.SearchText);
        Assert.Equal(["tasks"], page.VisibleGroups.Select(group => group.Id));
        Assert.All(page.Sections, section => Assert.True(section.IsVisible));
    }

    [Fact]
    public async Task The_selected_section_survives_a_reload()
    {
        var page = await LoadedAsync();
        page.Select("speakers");

        await page.Settings.LoadAsync();

        Assert.Equal("speakers", page.SelectedSection!.Id);
        Assert.Equal(["speakers"], page.VisibleGroups.Select(group => group.Id));
    }

    [Fact]
    public async Task Loading_fills_the_lists_and_storage()
    {
        var page = await LoadedAsync();

        var model = Editor(page, "WHISPER_MODEL");
        Assert.Equal(["large-v3-turbo", "small"], model.Options.Select(option => option.Value));
        Assert.False(model.IsNotInstalled);
        Assert.True(Editor(page, "OLLAMA_MODEL").OptionsUnreachable);
        Assert.Contains("options", _client.Calls);
        Assert.Equal(@"C:\data\vozata.db", page.Storage.DatabasePath);
        Assert.DoesNotContain(_client.Calls, call => call.StartsWith("test", StringComparison.Ordinal)); // never on open
    }

    [Fact]
    public async Task Lists_come_back_after_a_settings_reload()
    {
        var page = await LoadedAsync();

        await page.Settings.LoadAsync();

        Assert.Equal(2, Editor(page, "WHISPER_MODEL").Options.Count);
    }

    [Fact]
    public async Task Restore_defaults_puts_the_defaults_of_the_open_section_back_as_unsaved_changes()
    {
        _client.SettingValues["MIX_MODE"] = "stereo"; // saved differently from its default (mono)
        var page = await LoadedAsync();
        page.Select("audio");
        Assert.Equal("stereo", Editor(page, "MIX_MODE").SelectedChoice!.Value);

        page.RestoreDefaultsCommand.Execute(null);

        var mix = Editor(page, "MIX_MODE");
        Assert.Equal("mono", mix.SelectedChoice!.Value);
        Assert.True(mix.IsDirty);
        Assert.True(page.Settings.IsDirty);
        Assert.Empty(_client.Updates); // nothing is saved until the user says so
        await page.Settings.SaveCommand.ExecuteAsync(null);
        Assert.Equal("mono", (string)_client.Updates.Single()["MIX_MODE"]!);
    }

    [Fact]
    public async Task Discard_undoes_the_restored_defaults()
    {
        _client.SettingValues["MIX_MODE"] = "stereo";
        var page = await LoadedAsync();
        page.Select("audio");
        page.RestoreDefaultsCommand.Execute(null);

        page.Settings.DiscardCommand.Execute(null);

        Assert.Equal("stereo", Editor(page, "MIX_MODE").SelectedChoice!.Value);
        Assert.False(page.Settings.IsDirty);
    }

    [Fact]
    public async Task Restore_defaults_leaves_the_other_sections_alone()
    {
        _client.SettingValues["MIX_MODE"] = "stereo";
        _client.SettingValues["WHISPER_MODEL"] = "small"; // default: large-v3-turbo
        var page = await LoadedAsync();
        page.Select("audio");

        page.RestoreDefaultsCommand.Execute(null);

        Assert.Equal("small", Editor(page, "WHISPER_MODEL").TextValue);
        Assert.False(Editor(page, "WHISPER_MODEL").IsDirty);
    }

    [Fact]
    public async Task Restore_defaults_never_touches_a_secret()
    {
        var page = await LoadedAsync();
        page.Select("speakers");
        var token = Editor(page, "HF_TOKEN");
        token.ReplaceSecretCommand.Execute(null);
        token.TextValue = "hf_new";

        page.RestoreDefaultsCommand.Execute(null);

        Assert.Equal("hf_new", token.TextValue);
        Assert.True(token.IsReplacingSecret);
    }

    [Fact]
    public async Task Restore_defaults_is_only_for_an_open_engine_section()
    {
        var page = await LoadedAsync();
        Assert.True(page.RestoreDefaultsCommand.CanExecute(null)); // "general" is open

        page.Select("storage");
        Assert.False(page.RestoreDefaultsCommand.CanExecute(null));

        page.Select("audio");
        page.SearchText = "model";
        Assert.False(page.RestoreDefaultsCommand.CanExecute(null)); // a search shows pieces of many sections
    }

    private void OllamaServerNowAnswers() =>
        _client.Options = new SettingOptions(
            new Dictionary<string, IReadOnlyList<SettingOption>>
            {
                ["whisper_models"] = [new("large-v3-turbo", "large-v3-turbo")],
                ["ollama_models"] = [new("llama3.2:3b", "llama3.2:3b"), new("qwen2.5:7b", "qwen2.5:7b")],
            },
            new Dictionary<string, bool> { ["ollama_models"] = true });

    private int OptionRequests => _client.Calls.Count(call => call == "options");

    [Fact]
    public async Task Saving_a_new_Ollama_URL_reads_the_models_of_that_server()
    {
        var page = await LoadedAsync(); // the server did not answer when the app opened
        var model = Editor(page, "OLLAMA_MODEL");
        Assert.True(model.OptionsUnreachable);
        OllamaServerNowAnswers();

        Editor(page, "OLLAMA_URL").TextValue = "http://192.168.1.50:11434";
        await page.Settings.SaveCommand.ExecuteAsync(null);

        Assert.Equal(2, OptionRequests);
        Assert.False(model.OptionsUnreachable);
        Assert.Equal(["llama3.2:3b", "qwen2.5:7b"], model.Options.Select(option => option.Value));
    }

    [Fact]
    public async Task Saving_other_settings_does_not_read_the_lists_again()
    {
        var page = await LoadedAsync();

        var mix = Editor(page, "MIX_MODE");
        mix.SelectedChoice = mix.Choices.Single(choice => choice.Value == "stereo");
        await page.Settings.SaveCommand.ExecuteAsync(null);

        Assert.Equal(1, OptionRequests);
    }

    [Fact]
    public async Task Testing_the_Ollama_connection_reads_the_models_again()
    {
        var page = await LoadedAsync();
        OllamaServerNowAnswers();

        await Editor(page, "OLLAMA_URL").Test!.RunCommand.ExecuteAsync(null);

        Assert.Equal(2, OptionRequests);
        Assert.Equal(["llama3.2:3b", "qwen2.5:7b"], Editor(page, "OLLAMA_MODEL").Options.Select(option => option.Value));
    }

    [Fact]
    public async Task Testing_another_service_does_not_read_the_lists_again()
    {
        var page = await LoadedAsync();

        await Editor(page, "HF_TOKEN").Test!.RunCommand.ExecuteAsync(null);

        Assert.Equal(1, OptionRequests);
    }

    [Fact]
    public async Task Without_lists_the_editors_stay_free_text()
    {
        _client.OptionsError = new EngineUnavailableException("refused", new HttpRequestException());

        var page = await LoadedAsync();

        var model = Editor(page, "WHISPER_MODEL");
        Assert.Empty(model.Options);
        Assert.False(model.IsNotInstalled);
        model.TextValue = "my-own-model";
        Assert.True(page.Settings.IsDirty);
    }

    [Fact]
    public async Task Test_buttons_sit_next_to_their_service_keys()
    {
        var page = await LoadedAsync();

        Assert.Equal(
            new Dictionary<string, string>
            {
                ["OPENAI_STT_URL"] = ConnectionTargets.SttApi,
                ["HF_TOKEN"] = ConnectionTargets.HfToken,
                ["OLLAMA_URL"] = ConnectionTargets.Ollama,
                ["AZDO_PAT"] = ConnectionTargets.AzureDevOps,
                ["GITHUB_TOKEN"] = ConnectionTargets.GitHub,
            },
            page.Settings.Editors.Where(editor => editor.HasTest).ToDictionary(editor => editor.Key, editor => editor.Test!.Target));
        Assert.Equal(_localization["ConnectionTest"], Editor(page, "HF_TOKEN").Test!.ButtonText);
    }

    [Fact]
    public async Task A_test_runs_then_shows_success()
    {
        var page = await LoadedAsync();
        var test = Editor(page, "OLLAMA_URL").Test!;
        _client.TestGate = new TaskCompletionSource();
        _client.TestResults[ConnectionTargets.Ollama] = new ConnectionTestResult(true, "Ollama answered.");

        var running = test.RunCommand.ExecuteAsync(null);
        Assert.True(test.IsRunning);
        Assert.False(test.HasResult);
        Assert.Equal(_localization["ConnectionTesting"], test.Message);
        Assert.False(test.RunCommand.CanExecute(null));
        _client.TestGate.SetResult();
        await running;

        Assert.False(test.IsRunning);
        Assert.True(test.IsOk);
        Assert.False(test.IsFailed);
        Assert.True(test.HasResult);
        Assert.Equal("Ollama answered.", test.Message);
        Assert.Equal([ConnectionTargets.Ollama], _client.Tests);
    }

    [Fact]
    public async Task A_failed_test_shows_the_engine_message()
    {
        var page = await LoadedAsync();
        var test = Editor(page, "HF_TOKEN").Test!;
        _client.TestResults[ConnectionTargets.HfToken] = new ConnectionTestResult(false, "Accept the terms of pyannote.");

        await test.RunCommand.ExecuteAsync(null);

        Assert.True(test.IsFailed);
        Assert.Equal("Accept the terms of pyannote.", test.Message);
    }

    [Theory]
    [InlineData(true)]
    [InlineData(false)]
    public async Task A_test_the_engine_cannot_run_is_a_failure(bool unavailable)
    {
        var page = await LoadedAsync();
        var test = Editor(page, "GITHUB_TOKEN").Test!;
        _client.TestError = unavailable
            ? new EngineUnavailableException("refused", new HttpRequestException())
            : new EngineApiException(System.Net.HttpStatusCode.UnprocessableEntity, "invalid_request", "Bad target");

        await test.RunCommand.ExecuteAsync(null);

        Assert.True(test.IsFailed);
        Assert.Equal(unavailable ? _localization["EngineUnavailable"] : "Bad target", test.Message);
    }

    [Fact]
    public async Task An_invalid_address_blocks_save_until_fixed()
    {
        var page = await LoadedAsync();
        var url = Editor(page, "OLLAMA_URL");

        url.TextValue = "localhost:11434";
        Assert.True(page.Settings.IsDirty);
        Assert.True(page.Settings.HasValidationErrors);
        Assert.False(page.Settings.SaveCommand.CanExecute(null));

        url.TextValue = "http://127.0.0.1:11434";
        Assert.True(page.Settings.SaveCommand.CanExecute(null));
        await page.Settings.SaveCommand.ExecuteAsync(null);
        Assert.Equal("http://127.0.0.1:11434", (string)_client.Updates.Single()["OLLAMA_URL"]!);
    }

    [Fact]
    public async Task Changed_editors_save_together_and_discard_resets_them()
    {
        _client.RestartKeys.Add("OUTPUT_DIR");
        var page = await LoadedAsync(new FakePathPicker());
        await Editor(page, "OUTPUT_DIR").BrowseCommand.ExecuteAsync(null);
        Editor(page, "WHISPER_MODEL").TextValue = "small";
        Editor(page, "HF_TOKEN").ReplaceSecretCommand.Execute(null);
        Editor(page, "HF_TOKEN").TextValue = "hf_new";
        Assert.Equal(3, page.Settings.Editors.Count(editor => editor.IsDirty));
        Assert.True(Editor(page, "WHISPER_MODEL").IsNotInstalled);

        page.Settings.DiscardCommand.Execute(null);
        Assert.False(page.Settings.IsDirty);
        Assert.Equal("recordings", Editor(page, "OUTPUT_DIR").TextValue);
        Assert.False(Editor(page, "HF_TOKEN").IsEditingSecret);

        Editor(page, "OUTPUT_DIR").TextValue = @"D:\Meetings";
        await page.Settings.SaveCommand.ExecuteAsync(null);
        Assert.Equal([@"D:\Meetings"], _client.Updates.Single().Values.Cast<string>());
        Assert.Equal([_localization["Setting_OUTPUT_DIR"]], page.Settings.RestartKeys);
    }

    [Fact]
    public async Task Storage_shows_backend_paths_and_sizes()
    {
        _client.Health = _client.Health with
        {
            Storage = new StorageStatus("sqlite", @"C:\Users\me\OneDrive\vozata.db", "In OneDrive!", 3 * 1024L * 1024 * 1024, 900),
        };

        var page = await LoadedAsync();
        var storage = page.Storage;

        Assert.Equal(_localization["StorageBackendSqlite"], storage.BackendText);
        Assert.True(storage.HasDatabase);
        Assert.Equal(_localization.Format("SizeGigabytes", 3.0), storage.DatabaseSizeText);
        Assert.Equal(_localization.Format("SizeBytes", 900L), storage.CacheSizeText);
        Assert.Equal("In OneDrive!", storage.Warning);
        Assert.True(storage.ClearCacheCommand.CanExecute(null));

        storage.OpenFolderCommand.Execute(null);
        Assert.Equal([@"C:\Users\me\OneDrive"], _shell.Opened);
    }

    [Fact]
    public async Task Folder_storage_has_no_database()
    {
        _client.Health = _client.Health with { Storage = new StorageStatus("files", null, null) };

        var page = await LoadedAsync();

        Assert.Equal(_localization["StorageBackendFiles"], page.Storage.BackendText);
        Assert.False(page.Storage.HasDatabase);
        Assert.False(page.Storage.OpenFolderCommand.CanExecute(null));
        Assert.Equal(_localization["StorageNoDatabase"], page.Storage.DatabaseSizeText);
        Assert.False(page.Storage.ClearCacheCommand.CanExecute(null)); // empty cache
    }

    [Fact]
    public async Task Clear_cache_asks_first_then_frees_the_bytes()
    {
        var page = await LoadedAsync();

        await page.Storage.ClearCacheCommand.ExecuteAsync(null);

        Assert.Equal([_localization["StorageClearCacheTitle"]], _dialogs.Asked);
        Assert.Contains("clear-cache", _client.Calls);
        Assert.Equal(_localization.Format("StorageCacheCleared", _localization.Format("SizeKilobytes", 1.5)), page.Storage.Message);
        Assert.Equal(0, page.Storage.CacheBytes);
        Assert.False(page.Storage.IsBusy);
    }

    [Fact]
    public async Task Clear_cache_declined_does_nothing()
    {
        _dialogs.Answer = false;
        var page = await LoadedAsync();

        await page.Storage.ClearCacheCommand.ExecuteAsync(null);

        Assert.DoesNotContain("clear-cache", _client.Calls);
        Assert.Null(page.Storage.Message);
    }

    [Fact]
    public async Task Clear_cache_errors_are_shown()
    {
        var page = await LoadedAsync();
        _client.ClearCacheError = new EngineUnavailableException("refused", new HttpRequestException());

        await page.Storage.ClearCacheCommand.ExecuteAsync(null);

        Assert.Equal(_localization["EngineUnavailable"], page.Storage.Error);
    }

    [Fact]
    public async Task Storage_load_errors_are_shown_and_refresh_retries()
    {
        _client.UnavailableHealthChecks = 1;
        var page = await LoadedAsync();
        Assert.Equal(_localization["EngineUnavailable"], page.Storage.Error);

        await page.Storage.RefreshCommand.ExecuteAsync(null);

        Assert.Null(page.Storage.Error);
        Assert.Equal(_localization.Format("SizeMegabytes", 5.0), page.Storage.DatabaseSizeText);
    }

    [Fact]
    public async Task An_engine_without_storage_info_leaves_the_section_empty()
    {
        _client.Health = _client.Health with { Storage = null };

        var page = await LoadedAsync();

        Assert.Equal("", page.Storage.BackendText);
        Assert.Null(page.Storage.Error);
    }

    [Fact]
    public async Task About_shows_versions_and_opens_licenses()
    {
        var page = await LoadedAsync();
        await page.About.Health.LoadAsync();

        Assert.False(string.IsNullOrEmpty(page.About.AppVersion));
        Assert.DoesNotContain('+', page.About.AppVersion);
        Assert.Equal("0.1.0", page.About.Health.EngineVersion);
        Assert.Contains(page.About.Licenses, link => link.Name.StartsWith("VozAta", StringComparison.Ordinal));
        Assert.Equal("Avalonia (MIT)", page.About.Licenses[1].ToString());

        page.About.OpenLinkCommand.Execute(page.About.Licenses[0]);
        page.About.OpenLinkCommand.Execute(null);

        Assert.Equal([page.About.Licenses[0].Url], _shell.Opened);
    }

    [Fact]
    public async Task Texts_follow_the_language()
    {
        var page = await LoadedAsync();

        _localization.SetLanguage("es");
        page.RefreshTexts();

        Assert.Equal(_localization["ConfigSection_about"], page.Sections[^1].Title);
        Assert.Equal(_localization["SettingsGroup_general"], page.Sections[0].Title);
        Assert.Equal(_localization["StorageBackendSqlite"], page.Storage.BackendText);
        Assert.Equal(_localization["ConnectionTest"], Editor(page, "OLLAMA_URL").Test!.ButtonText);
    }

    [Fact]
    public void Byte_sizes_use_the_largest_unit()
    {
        Assert.Equal(_localization.Format("SizeBytes", 12L), ByteSize.Format(12, _localization));
        Assert.Equal(_localization.Format("SizeKilobytes", 2.0), ByteSize.Format(2048, _localization));
        Assert.Equal(_localization.Format("SizeMegabytes", 1.0), ByteSize.Format(1024 * 1024, _localization));
        Assert.Equal(_localization.Format("SizeGigabytes", 1.0), ByteSize.Format(1024L * 1024 * 1024, _localization));
    }
}
