using System.Text.Json;
using VozAta.Client;
using VozAta.Desktop.Services;
using VozAta.Desktop.Tests.Fakes;
using VozAta.Desktop.ViewModels;

namespace VozAta.Desktop.Tests;

/// <summary>Minutes templates (phase 20): loaded from the engine, chosen at start and on regenerate.</summary>
public sealed class TemplateSelectionTests
{
    private const string Id = "20261016_090000";

    private readonly FakeEngineClient _client = new();
    private readonly LocalizationService _localization = new();

    public TemplateSelectionTests()
    {
        _client.Sessions.Add(new SessionSummary(Id, "done", null, null, 60, "pt", true));
        _client.Details[Id] = new SessionDetail(Id, "done", null, null, 60, "pt", true, [], @"C:\VozAta\recordings\x")
        {
            Metadata = new Dictionary<string, JsonElement> { ["template"] = JsonSerializer.SerializeToElement("daily") },
        };
        _client.Transcripts[Id] = new Transcript("raw", [new Segment("mic-000001", "mic", "mic", "Me", 1, 2, "Hi.", false, [])]);
    }

    private readonly FakeEngineEvents _events = new();

    private MainViewModel Create() =>
        new(_client, _events, new FakeEngineProcess(), new ImmediateDispatcher(), _localization, new FakeDialogs(),
            new FakePreferences(), new FakeClock(), new FakeTimer(), new FakeShell(), new FakeFileSaver(), new FakeThemeService());

    private async Task<MainViewModel> ReadyAsync()
    {
        var viewModel = Create();
        await viewModel.InitializeAsync();
        _events.Send(new ConnectionChangedEvent(true));
        for (var i = 0; i < 200 && viewModel.EngineStatus != EngineStatus.Connected; i++)
        {
            await Task.Delay(5);
        }

        return viewModel;
    }

    [Fact]
    public async Task The_template_list_is_loaded_and_the_configured_default_is_preselected()
    {
        _client.SettingValues["MINUTES_TEMPLATE"] = "daily";

        var viewModel = await ReadyAsync();

        Assert.Equal(["general", "daily", "client"], viewModel.Templates.Items.Select(item => item.Id));
        Assert.Equal("Daily stand-up", viewModel.SelectedTemplate!.Name);
        Assert.Contains("templates", _client.Calls);
    }

    [Fact]
    public async Task Without_a_known_default_the_first_template_is_selected()
    {
        _client.SettingValues["MINUTES_TEMPLATE"] = "weekly";

        var viewModel = await ReadyAsync();

        Assert.Equal("general", viewModel.SelectedTemplate!.Id);
    }

    [Fact]
    public async Task The_selected_template_is_sent_on_start()
    {
        var viewModel = await ReadyAsync();
        viewModel.SelectedTemplate = viewModel.Templates.Find("client");

        await viewModel.StartCommand.ExecuteAsync(null);

        Assert.Equal("client", _client.StartRequests.Single().Template);
    }

    [Fact]
    public async Task A_template_list_failure_is_shown_and_start_lets_the_engine_choose()
    {
        _client.TemplatesError = FakeEngineClient.ApiError("internal_error", "Templates unavailable.");

        var viewModel = await ReadyAsync();
        await viewModel.StartCommand.ExecuteAsync(null);

        Assert.Contains("Templates unavailable.", viewModel.Notifications);
        Assert.Null(viewModel.SelectedTemplate);
        Assert.Null(_client.StartRequests.Single().Template);
    }

    [Fact]
    public async Task A_language_change_renames_the_templates_and_keeps_the_selection()
    {
        var viewModel = await ReadyAsync();
        var selected = viewModel.Templates.Find("client");
        viewModel.SelectedTemplate = selected;
        _client.Templates[2] = new MinutesTemplate("client", "Reunião com cliente");

        viewModel.SelectedAppLanguage = viewModel.AppLanguages.Single(option => option.Value == "pt-BR");
        await viewModel.LanguageSave;

        Assert.Same(selected, viewModel.SelectedTemplate);
        Assert.Equal("Reunião com cliente", selected!.Name);
    }

    [Fact]
    public async Task A_saved_default_template_is_selected_and_a_saved_language_reloads_the_names()
    {
        _client.Schema.Add(Choice("APP_LANGUAGE", "en", "pt-BR", "es"));
        _client.Schema.Add(Choice("MINUTES_TEMPLATE", "general", "daily", "client"));
        _client.SettingValues["MINUTES_TEMPLATE"] = "general";
        var viewModel = await ReadyAsync();
        var editors = viewModel.Settings.Groups.Single().Editors;
        editors[0].SelectedChoice = editors[0].Choices.Single(choice => choice.Value == "es");
        editors[1].SelectedChoice = editors[1].Choices.Single(choice => choice.Value == "daily");
        _client.Templates[1] = new MinutesTemplate("daily", "Daily");

        await viewModel.Settings.SaveCommand.ExecuteAsync(null);
        await viewModel.TemplatesRefresh;

        Assert.Equal("daily", viewModel.SelectedTemplate!.Id);
        Assert.Equal("Daily", viewModel.SelectedTemplate.Name);
    }

    [Fact]
    public async Task Regenerate_preselects_the_session_template_and_sends_the_chosen_one()
    {
        var viewModel = await ReadyAsync();
        viewModel.History.Selected = viewModel.History.Rows[0];
        await viewModel.History.DetailLoading;
        var detail = viewModel.History.Detail!;

        Assert.Equal(["general", "daily", "client"], detail.Templates.Select(item => item.Id));
        Assert.Equal("daily", detail.RegenerateTemplate!.Id);
        await detail.RegenerateMinutesCommand.ExecuteAsync(null);
        detail.RegenerateTemplate = viewModel.Templates.Find("client");
        await detail.RegenerateMinutesCommand.ExecuteAsync(null);

        Assert.Equal(["daily", "client"], _client.RegeneratedTemplates);
    }

    [Fact]
    public async Task A_detail_without_templates_regenerates_with_the_session_template()
    {
        var detail = new SessionDetailViewModel(_client, new FakeShell(), _localization, new FakeFileSaver(), _client.Sessions[0]);

        await detail.LoadAsync();
        await detail.RegenerateMinutesCommand.ExecuteAsync(null);

        Assert.Empty(detail.Templates);
        Assert.Null(detail.RegenerateTemplate);
        Assert.Equal([(string?)null], _client.RegeneratedTemplates);
    }

    [Fact]
    public async Task Reloading_removes_templates_the_engine_no_longer_has_and_inserts_new_ones()
    {
        var templates = new MinutesTemplatesViewModel(_client);
        await templates.LoadAsync();
        var general = templates.Find("general");
        _client.Templates.RemoveAt(1);
        _client.Templates.Insert(1, new MinutesTemplate("retrospective", "Retrospective"));

        await templates.LoadAsync();

        Assert.Equal(["general", "retrospective", "client"], templates.Items.Select(item => item.Id));
        Assert.Same(general, templates.Find("general"));
        Assert.Equal("Retrospective", templates.Items[1].ToString());
    }

    private static SettingSchema Choice(string key, params string[] choices) =>
        new(key, "choice", JsonSerializer.SerializeToElement(choices[0]), choices, false, "general");
}
