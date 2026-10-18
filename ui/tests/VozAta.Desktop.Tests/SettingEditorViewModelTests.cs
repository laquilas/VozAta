using System.Text.Json;
using VozAta.Client;
using VozAta.Desktop.Services;
using VozAta.Desktop.Tests.Fakes;
using VozAta.Desktop.ViewModels;

namespace VozAta.Desktop.Tests;

/// <summary>The phase 38 editors: option lists, paths, URLs, secrets, badges and search.</summary>
public sealed class SettingEditorViewModelTests
{
    private readonly LocalizationService _localization = new();

    private SettingEditorViewModel Editor(
        string key, string type, object? value, string? source = null, string[]? choices = null, bool secret = false,
        IPathPicker? paths = null, object? fallback = null) =>
        new(
            new SettingSchema(key, type, JsonSerializer.SerializeToElement(fallback), choices, secret, "general", "next_session", source),
            JsonSerializer.SerializeToElement(value),
            _localization,
            paths);

    private static SettingOption[] Models() =>
        [new("large-v3-turbo", "large-v3-turbo", true), new("small", "small", false)];

    [Fact]
    public void A_key_with_an_options_source_is_an_options_editor()
    {
        var editor = Editor("WHISPER_MODEL", "string", "large-v3-turbo", "whisper_models");

        Assert.Equal(SettingKind.Options, editor.Kind);
        Assert.True(editor.IsOptions);
        Assert.False(editor.IsText);
        Assert.Empty(editor.Options);
        Assert.False(editor.IsNotInstalled); // no list yet: nothing to compare with
    }

    [Fact]
    public void The_list_is_offered_and_an_installed_value_is_fine()
    {
        var editor = Editor("WHISPER_MODEL", "string", "large-v3-turbo", "whisper_models");

        editor.SetOptions(Models(), reachable: true);

        Assert.Equal(["large-v3-turbo", "small"], editor.Options.Select(option => option.Value));
        Assert.False(editor.Options[1].IsAvailable);
        Assert.False(editor.IsNotInstalled);
        Assert.False(editor.OptionsUnreachable);
        Assert.Equal("small", editor.Options[1].ToString()); // what the editable combo box types
    }

    [Fact]
    public void An_unknown_value_is_kept_and_flagged_not_installed()
    {
        var editor = Editor("OLLAMA_MODEL", "string", "mistral:7b", "ollama_models");

        editor.SetOptions([new SettingOption("qwen2.5:7b", "qwen2.5:7b")], reachable: true);

        Assert.Equal("mistral:7b", editor.TextValue);
        Assert.True(editor.IsNotInstalled);
        Assert.False(editor.IsDirty);
        editor.TextValue = "qwen2.5:7b";
        Assert.False(editor.IsNotInstalled);
        Assert.Equal("qwen2.5:7b", editor.ToJson());
    }

    [Fact]
    public void A_listed_but_not_downloaded_model_is_flagged()
    {
        var editor = Editor("WHISPER_MODEL", "string", "small", "whisper_models");

        editor.SetOptions(Models(), reachable: true);

        Assert.True(editor.IsNotInstalled);
    }

    [Fact]
    public void An_unreachable_service_is_said_and_nothing_is_flagged()
    {
        var editor = Editor("OLLAMA_MODEL", "string", "qwen2.5:7b", "ollama_models");

        editor.SetOptions([], reachable: false);

        Assert.True(editor.OptionsUnreachable);
        Assert.False(editor.IsNotInstalled);
    }

    [Fact]
    public void A_choice_with_a_source_marks_unavailable_entries()
    {
        var editor = Editor("WHISPER_DEVICE", "choice", "cuda", "devices", ["auto", "cuda", "cpu"]);
        Assert.Equal(SettingKind.Choice, editor.Kind);

        editor.SetOptions([new("auto", "auto"), new("cuda", "cuda", false), new("cpu", "cpu")], reachable: true);

        Assert.Equal([true, false, true], editor.Choices.Select(choice => choice.IsAvailable));
        Assert.True(editor.IsNotInstalled);
        editor.SelectedChoice = editor.Choices[2];
        Assert.False(editor.IsNotInstalled);
    }

    [Fact]
    public void A_choice_missing_from_the_list_stays_available()
    {
        var editor = Editor("WHISPER_DEVICE", "choice", "auto", "devices", ["auto", "cuda", "cpu"]);

        editor.SetOptions([new("cuda", "cuda", false)], reachable: true);

        Assert.True(editor.Choices[0].IsAvailable);
    }

    [Theory]
    [InlineData("OUTPUT_DIR", "folder", @"D:\Meetings")]
    [InlineData("TRANSLATION_MODEL_DIR", "folder", @"D:\Meetings")]
    [InlineData("VOCABULARY_FILE", "file", @"D:\Lists\terms.txt")]
    public async Task Browse_puts_the_chosen_path_in_the_box(string key, string kind, string expected)
    {
        var paths = new FakePathPicker();
        var editor = Editor(key, "path", @"C:\old\place", paths: paths);
        Assert.True(editor.IsPath);

        await editor.BrowseCommand.ExecuteAsync(null);

        Assert.Equal(expected, editor.TextValue);
        Assert.True(editor.IsDirty);
        var call = Assert.Single(paths.Calls);
        Assert.Equal((kind, editor.Label, @"C:\old\place"), call);
    }

    [Fact]
    public async Task Browse_for_the_database_keeps_its_file_name()
    {
        var paths = new FakePathPicker();
        var editor = Editor("DATABASE_PATH", "path", @"C:\data\meetings.db", paths: paths);

        await editor.BrowseCommand.ExecuteAsync(null);

        Assert.Equal(Path.Combine(@"D:\Meetings", "meetings.db"), editor.TextValue);
        Assert.Equal(@"C:\data", paths.Calls.Single().Start);
    }

    [Fact]
    public async Task Browse_for_an_unset_database_uses_the_default_name()
    {
        var paths = new FakePathPicker();
        var editor = Editor("DATABASE_PATH", "path", null, paths: paths);

        await editor.BrowseCommand.ExecuteAsync(null);

        Assert.Equal(Path.Combine(@"D:\Meetings", "vozata.db"), editor.TextValue);
        Assert.Null(paths.Calls.Single().Start);
    }

    [Fact]
    public async Task Browse_for_a_file_named_by_the_default()
    {
        var paths = new FakePathPicker();
        var editor = Editor("DATABASE_PATH", "path", "", paths: paths, fallback: @"recordings\store.db");

        await editor.BrowseCommand.ExecuteAsync(null);

        Assert.Equal(Path.Combine(@"D:\Meetings", "store.db"), editor.TextValue);
    }

    [Fact]
    public async Task A_cancelled_browse_changes_nothing()
    {
        var paths = new FakePathPicker { Folder = null };
        var editor = Editor("OUTPUT_DIR", "path", "recordings", paths: paths);

        await editor.BrowseCommand.ExecuteAsync(null);

        Assert.Equal("recordings", editor.TextValue);
        Assert.False(editor.IsDirty);
    }

    [Fact]
    public void Without_a_picker_browse_is_disabled()
    {
        var editor = Editor("OUTPUT_DIR", "path", "recordings");

        Assert.False(editor.BrowseCommand.CanExecute(null));
    }

    [Theory]
    [InlineData("http://localhost:11434", false)]
    [InlineData("https://api.openai.com/v1", false)]
    [InlineData("", false)]
    [InlineData("localhost:11434", true)]
    [InlineData("ftp://files.example.com", true)]
    [InlineData("not a url", true)]
    public void Addresses_are_validated_while_typing(string text, bool invalid)
    {
        var editor = Editor("OLLAMA_URL", "url", "http://localhost:11434");

        editor.TextValue = text;

        Assert.Equal(invalid, editor.HasValidationError);
        Assert.Equal(invalid ? _localization["SettingInvalidUrl"] : null, editor.ValidationError);
        Assert.True(editor.IsText);
    }

    [Fact]
    public void The_url_message_follows_the_language()
    {
        var editor = Editor("OLLAMA_URL", "url", "nope");
        _localization.SetLanguage("pt-BR");

        editor.RefreshTexts(_localization);

        Assert.Equal(_localization["SettingInvalidUrl"], editor.ValidationError);
    }

    [Fact]
    public void A_stored_secret_is_never_shown_and_untouched_is_not_dirty()
    {
        var editor = Editor("HF_TOKEN", "string", "********", secret: true);

        Assert.Equal("", editor.TextValue);
        Assert.True(editor.HasStoredSecret);
        Assert.False(editor.IsEditingSecret);
        Assert.Equal(_localization["SecretStored"], editor.SecretStatus);
        Assert.False(editor.IsDirty);
    }

    [Fact]
    public void Replace_opens_an_empty_box_and_sends_the_new_value()
    {
        var editor = Editor("HF_TOKEN", "string", "********", secret: true);

        editor.ReplaceSecretCommand.Execute(null);
        Assert.True(editor.IsEditingSecret);
        Assert.False(editor.IsDirty); // nothing typed yet: the stored value stays
        editor.TextValue = "hf_new";

        Assert.True(editor.IsDirty);
        Assert.Equal("hf_new", editor.ToJson());
    }

    [Fact]
    public void Remove_clears_the_secret_on_save_and_keep_undoes_it()
    {
        var editor = Editor("GITHUB_TOKEN", "string", "********", secret: true);

        editor.RemoveSecretCommand.Execute(null);
        Assert.True(editor.IsDirty);
        Assert.Null(editor.ToJson());
        Assert.False(editor.IsEditingSecret);
        Assert.Equal(_localization["SecretWillBeRemoved"], editor.SecretStatus);

        editor.KeepSecretCommand.Execute(null);
        Assert.False(editor.IsDirty);
        Assert.False(editor.IsRemovingSecret);
    }

    [Fact]
    public void An_unset_secret_is_typed_directly()
    {
        var editor = Editor("AZDO_PAT", "string", null, secret: true);

        Assert.False(editor.HasStoredSecret);
        Assert.True(editor.IsEditingSecret);
        Assert.Equal(_localization["SecretNotSet"], editor.SecretStatus);
        editor.TextValue = "pat";
        Assert.Equal("pat", editor.ToJson());
        editor.TextValue = " ";
        Assert.False(editor.IsDirty);
    }

    [Fact]
    public void Search_matches_label_key_and_help()
    {
        var editor = Editor("CHUNK_SECONDS", "number", 5.0);

        Assert.True(editor.Matches(""));
        Assert.True(editor.Matches("chunk_sec"));
        Assert.True(editor.Matches(editor.Label.ToUpperInvariant()));
        Assert.True(editor.Matches(editor.Help[..12]));
        Assert.False(editor.Matches("zzz-nothing"));
    }

    [Fact]
    public void Choice_labels_without_a_resource_are_the_value()
    {
        var choice = new SettingChoice("mono", null);
        choice.Refresh(_localization);

        Assert.Equal(("mono", "mono"), (choice.Label, choice.ToString()));
    }
}
