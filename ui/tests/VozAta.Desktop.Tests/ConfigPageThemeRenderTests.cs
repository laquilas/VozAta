using System.Text.Json;
using VozAta.Client;
using VozAta.Desktop.Tests.Fakes;
using VozAta.Desktop.ViewModels;
using VozAta.Desktop.Views;

namespace VozAta.Desktop.Tests;

/// <summary>
/// The Config page (phase 38) on the headless platform in light and dark: an engine section with
/// option lists, badges and a test result, a search across sections, and the Storage section.
/// With <c>VOZATA_SCREENSHOTS</c> set, the frames are saved as PNG.
/// </summary>
public sealed class ConfigPageThemeRenderTests
{
    [Theory]
    [InlineData("light")]
    [InlineData("dark")]
    public async Task The_config_page_renders_in_the_theme(string theme)
    {
        var rendered = await ThemeRenderTests.Session.Value.Dispatch<int>(
            async () =>
            {
                var viewModel = await ThemeRenderTests.SeededAsync(theme, Seed);
                var config = viewModel.Config;
                viewModel.Notifications.Clear(); // the toast would hide the Save bar

                config.Select("minutes");
                var model = config.Settings.Editors.Single(editor => editor.Key == "OLLAMA_MODEL");
                model.TextValue = "mistral:7b"; // changed and not installed
                await config.Settings.Editors.Single(editor => editor.Key == "OLLAMA_URL").Test!.RunCommand.ExecuteAsync(null);
                ThemeRenderTests.Render<ConfigPage>(viewModel, ShellViewModel.Config, $"config-minutes-{theme}.png");

                config.Select("speakers");
                await config.Settings.Editors.Single(editor => editor.Key == "HF_TOKEN").Test!.RunCommand.ExecuteAsync(null);
                ThemeRenderTests.Render<ConfigPage>(viewModel, ShellViewModel.Config, $"config-speakers-{theme}.png");

                config.Settings.DiscardCommand.Execute(null);
                config.SearchText = "model";
                ThemeRenderTests.Render<ConfigPage>(viewModel, ShellViewModel.Config, $"config-search-{theme}.png");

                config.Select("storage");
                ThemeRenderTests.Render<ConfigPage>(viewModel, ShellViewModel.Config, $"config-storage-{theme}.png");

                config.Select("about");
                ThemeRenderTests.Render<ConfigPage>(viewModel, ShellViewModel.Config, $"config-about-{theme}.png");
                return 5;
            },
            CancellationToken.None);

        Assert.Equal(5, rendered);
    }

    private static void Seed(FakeEngineClient client)
    {
        Add(client, "OUTPUT_DIR", "path", @"C:\Users\me\Documents\VozAta", "general", applies: "restart");
        client.Schema.RemoveAll(item => item.Key == "WHISPER_MODEL"); // the shared seed has it without a list
        Add(client, "WHISPER_MODEL", "string", "large-v3-turbo", "transcription", applies: "restart", source: "whisper_models");
        Add(client, "WHISPER_DEVICE", "choice", "cuda", "transcription", ["auto", "cuda", "cpu"], "restart", source: "devices");
        Add(client, "HF_TOKEN", "string", "********", "speakers", secret: true);
        Add(client, "DIARIZATION_ENABLED", "bool", true, "speakers");
        Add(client, "LLM_PROVIDER", "string", "ollama", "minutes", source: "llm_providers");
        Add(client, "OLLAMA_URL", "url", "http://localhost:11434", "minutes");
        Add(client, "OLLAMA_MODEL", "string", "qwen2.5:7b", "minutes", source: "ollama_models");
        Add(client, "GITHUB_TOKEN", "string", null, "tasks", secret: true);
        client.Options = new SettingOptions(
            new Dictionary<string, IReadOnlyList<SettingOption>>
            {
                ["whisper_models"] = [new("large-v3-turbo", "large-v3-turbo"), new("small", "small", false)],
                ["devices"] = [new("auto", "auto"), new("cuda", "cuda"), new("cpu", "cpu")],
                ["llm_providers"] = [new("ollama", "ollama")],
                ["ollama_models"] = [new("qwen2.5:7b", "qwen2.5:7b"), new("llama3.2:3b", "llama3.2:3b")],
            },
            new Dictionary<string, bool> { ["ollama_models"] = true });
        client.TestResults[ConnectionTargets.Ollama] = new ConnectionTestResult(true, "Ollama answered and the model qwen2.5:7b is installed.");
        client.TestResults[ConnectionTargets.HfToken] = new ConnectionTestResult(
            false, "The token works, but its account has not accepted the terms of pyannote/speaker-diarization-community-1.");
        client.Health = client.Health with
        {
            Storage = new StorageStatus(
                "sqlite",
                @"C:\Users\me\OneDrive\Documents\VozAta\vozata.db",
                "The database is in a OneDrive folder. OneDrive can lock or corrupt it while VozAta runs: set DATABASE_PATH to a folder outside OneDrive and restart the engine.",
                734L * 1024 * 1024,
                212L * 1024 * 1024),
        };
    }

    private static void Add(
        FakeEngineClient client, string key, string type, object? value, string group, string[]? choices = null,
        string applies = "next_session", bool secret = false, string? source = null)
    {
        client.Schema.Add(new SettingSchema(key, type, JsonSerializer.SerializeToElement(value), choices, secret, group, applies, source));
        client.SettingValues[key] = value;
    }
}
