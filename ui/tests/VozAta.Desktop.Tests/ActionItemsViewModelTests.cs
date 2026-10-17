using System.Net;
using VozAta.Client;
using VozAta.Desktop.Services;
using VozAta.Desktop.Tests.Fakes;
using VozAta.Desktop.ViewModels;

namespace VozAta.Desktop.Tests;

public sealed class ActionItemsViewModelTests
{
    private const string Id = "20261016_090000";

    private readonly FakeEngineClient _client = new();
    private readonly LocalizationService _localization = new();
    private readonly FakeShell _shell = new();

    public ActionItemsViewModelTests()
    {
        _client.ActionItems[Id] =
        [
            new ActionItem("a1", "Send the report", "Ana", "2026-10-20", ["mic-000002"], null),
            new ActionItem("a2", "Book the room", null, null, [], null),
            new ActionItem("a3", "Old task", null, null, [], "https://github.test/old"),
        ];
    }

    private ActionItemsViewModel Create() => new(_client, _localization, _shell, Id);

    private async Task<ActionItemsViewModel> LoadedAsync()
    {
        var model = Create();
        await model.LoadAsync();
        return model;
    }

    [Fact]
    public async Task Load_shows_items_targets_and_disables_exported_items()
    {
        var model = await LoadedAsync();

        Assert.Equal(["a1", "a2", "a3"], model.Items.Select(row => row.Id));
        Assert.Equal(("Ana", "2026-10-20"), (model.Items[0].Owner, model.Items[0].Due));
        Assert.Equal(("", ""), (model.Items[1].Owner, model.Items[1].Due));
        Assert.True(model.Items[0].IsEditable);
        Assert.False(model.Items[2].IsEditable);
        Assert.True(model.Items[2].IsExported);
        Assert.Equal(["Azure DevOps", "GitHub Issues"], model.Targets.Select(target => target.Label));
        Assert.Equal("azure_devops", model.SelectedTarget?.Id);
        Assert.Equal("Azure DevOps", model.SelectedTarget?.ToString());
        Assert.True(model.HasItems);
        Assert.True(model.HasTargets);
        Assert.False(model.IsEmpty);
    }

    [Fact]
    public async Task Without_items_or_targets_the_tab_says_so()
    {
        _client.ActionItems[Id].Clear();
        _client.TaskTargets.Clear();

        var model = await LoadedAsync();

        Assert.True(model.IsEmpty);
        Assert.False(model.HasTargets);
        Assert.Null(model.SelectedTarget);
    }

    [Fact]
    public async Task Export_needs_a_selected_item_that_is_not_exported_and_a_target()
    {
        var model = await LoadedAsync();
        Assert.False(model.ExportCommand.CanExecute(null));

        model.Items[2].IsSelected = true; // exported: does not count
        Assert.False(model.ExportCommand.CanExecute(null));

        model.Items[0].IsSelected = true;
        Assert.True(model.ExportCommand.CanExecute(null));

        model.SelectedTarget = null;
        Assert.False(model.ExportCommand.CanExecute(null));
    }

    [Fact]
    public async Task Export_sends_the_edits_then_the_selected_items_and_shows_the_links()
    {
        var model = await LoadedAsync();
        model.SelectedTarget = model.Targets[1];
        model.Items[0].Description = "  Send the final report ";
        model.Items[0].Owner = " ";
        model.Items[1].Due = "Friday";
        model.Items[0].IsSelected = true;

        await model.ExportCommand.ExecuteAsync(null);

        var (_, edits) = Assert.Single(_client.ActionItemUpdates);
        Assert.Equal(
            [new ActionItemEdit("a1", "Send the final report", null, "2026-10-20"), new ActionItemEdit("a2", "Book the room", null, "Friday")],
            edits);
        var export = Assert.Single(_client.ActionItemExports);
        Assert.Equal((Id, "github"), (export.Id, export.Target));
        Assert.Equal(["a1"], export.ItemIds);
        Assert.Equal("https://github.test/a1", model.Items[0].ExportedUrl);
        Assert.False(model.Items[0].IsSelected);
        Assert.False(model.Items[0].IsEditable);
        Assert.Equal("Send the final report", model.Items[0].Description);
        Assert.Equal("Exported: 1.", model.Message);
        Assert.Null(model.Error);
        Assert.False(model.ExportCommand.CanExecute(null));
        Assert.Equal("github", model.SelectedTarget?.Id); // kept after the reload
    }

    [Fact]
    public async Task Failed_items_show_the_engine_reason()
    {
        _client.ExportFailures["a2"] = "GitHub rejected the credentials (HTTP 401).";
        var model = await LoadedAsync();
        model.Items[0].IsSelected = true;
        model.Items[1].IsSelected = true;

        await model.ExportCommand.ExecuteAsync(null);

        Assert.Null(model.Items[0].Error);
        Assert.Equal("GitHub rejected the credentials (HTTP 401).", model.Items[1].Error);
        Assert.True(model.Items[1].IsSelected); // still selected for a retry
        Assert.Equal("Exported: 1.", model.Message);
        Assert.Equal("Not exported: 1. The reason is shown under each item.", model.Error);
    }

    [Fact]
    public async Task An_engine_error_during_export_is_shown()
    {
        _client.ActionItemsExportError = new EngineApiException(HttpStatusCode.UnprocessableEntity, "unknown_task_target", "Not configured.");
        var model = await LoadedAsync();
        model.Items[0].IsSelected = true;

        await model.ExportCommand.ExecuteAsync(null);

        Assert.Equal("Not configured.", model.Error);
        Assert.False(model.IsExporting);
        Assert.Null(model.Items[0].ExportedUrl);
    }

    [Fact]
    public async Task Exporting_only_exported_rows_skips_the_edit_call()
    {
        _client.ActionItems[Id].RemoveRange(0, 2);
        var model = await LoadedAsync();
        model.Items[0].IsSelected = true;

        Assert.False(model.ExportCommand.CanExecute(null));
        Assert.Empty(_client.ActionItemUpdates);
    }

    [Fact]
    public async Task Load_errors_are_shown_and_an_unreachable_engine_is_explained()
    {
        _client.ActionItemsError = new EngineUnavailableException("down", new HttpRequestException());

        var model = await LoadedAsync();

        Assert.Equal(_localization["EngineUnavailable"], model.Error);
        Assert.False(model.IsLoading);
    }

    [Fact]
    public async Task Extract_waits_for_the_ready_event_then_reloads()
    {
        var model = await LoadedAsync();

        await model.ExtractCommand.ExecuteAsync(null);

        Assert.Equal([Id], _client.Extractions);
        Assert.True(model.IsExtracting);
        Assert.False(model.ExtractCommand.CanExecute(null));
        _client.ActionItems[Id].Add(new ActionItem("a4", "New", null, null, [], null));

        await model.OnReadyAsync("other-session");
        Assert.True(model.IsExtracting);

        await model.OnReadyAsync(Id);
        Assert.False(model.IsExtracting);
        Assert.Equal(4, model.Items.Count);
    }

    [Fact]
    public async Task An_error_event_ends_our_extraction()
    {
        var model = await LoadedAsync();
        await model.ExtractCommand.ExecuteAsync(null);

        model.OnError("other-session", "nope");
        Assert.True(model.IsExtracting);
        model.OnError(Id, "Ollama is down.");

        Assert.False(model.IsExtracting);
        Assert.Equal("Ollama is down.", model.Error);
        model.OnError(Id, "ignored when not extracting");
        Assert.Equal("Ollama is down.", model.Error);
    }

    [Fact]
    public async Task A_refused_extraction_shows_the_engine_message()
    {
        var model = await LoadedAsync();
        _client.ActionItemsError = new EngineApiException(HttpStatusCode.Conflict, "action_items_still_recording", "Still recording.");

        await model.ExtractCommand.ExecuteAsync(null);

        Assert.False(model.IsExtracting);
        Assert.Equal("Still recording.", model.Error);
    }

    [Fact]
    public void A_live_session_cannot_extract()
    {
        var model = Create();
        model.IsLive = true;

        Assert.False(model.ExtractCommand.CanExecute(null));
    }

    [Fact]
    public async Task Links_open_in_the_browser()
    {
        var model = await LoadedAsync();

        model.OpenLinkCommand.Execute(model.Items[2].ExportedUrl);
        model.OpenLinkCommand.Execute(null);

        Assert.Equal(["https://github.test/old"], _shell.Opened);
    }

    [Fact]
    public async Task Rows_of_a_reload_no_longer_notify_the_old_selection()
    {
        var model = await LoadedAsync();
        var old = model.Items[0];
        await model.LoadAsync();

        old.IsSelected = true;

        Assert.False(model.ExportCommand.CanExecute(null));
    }
}
