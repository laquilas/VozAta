using VozAta.Client;
using VozAta.Desktop.Services;
using VozAta.Desktop.Tests.Fakes;
using VozAta.Desktop.ViewModels;

namespace VozAta.Desktop.Tests;

/// <summary>The import banner of phase 33: progress, pause, the end with counts and errors.</summary>
public sealed class MigrationViewModelTests
{
    private readonly FakeEngineClient _client = new();
    private readonly LocalizationService _localization = new();
    private int _reloads;

    private MigrationViewModel Create() => new(_client, _localization, () =>
    {
        _reloads++;
        return Task.CompletedTask;
    });

    private static MigrationSummary Summary(
        string state, int done = 0, int total = 0, int imported = 0, bool paused = false,
        string? message = null, params MigrationFolderError[] errors) =>
        new(state, done, total, null, paused, imported, errors.Length, null, null, message, errors);

    private static readonly MigrationFolderError Bad =
        new(@"C:\rec\20261015_202358", "unreadable_json", "A file could not be read.", "boom");

    [Fact]
    public async Task A_disabled_or_idle_import_shows_nothing()
    {
        var viewModel = Create();

        await viewModel.RefreshAsync();
        _client.Migration = Summary("idle");
        await viewModel.RefreshAsync();
        _client.Migration = Summary("done"); // nothing imported in this run: old news
        await viewModel.RefreshAsync();

        Assert.False(viewModel.IsVisible);
        Assert.Equal(0, _reloads);
    }

    [Fact]
    public void Progress_shows_the_banner_with_n_of_m()
    {
        var viewModel = Create();

        viewModel.OnProgress(new MigrationProgressEvent(null, 1, 4, "20261015_202358", false));

        Assert.True(viewModel.IsVisible);
        Assert.True(viewModel.IsRunning);
        Assert.Equal(_localization.Format("MigrationProgress", 1, 4), viewModel.Text);
        Assert.Equal(25, viewModel.Progress);
    }

    [Fact]
    public void A_paused_import_says_so()
    {
        var viewModel = Create();

        viewModel.OnProgress(new MigrationProgressEvent(null, 2, 4, "x", true));

        Assert.Equal(_localization.Format("MigrationPaused", 2, 4), viewModel.Text);
    }

    [Fact]
    public async Task A_running_import_found_on_connect_shows_its_progress()
    {
        _client.Migration = Summary("running", done: 3, total: 10);
        var viewModel = Create();

        await viewModel.RefreshAsync();

        Assert.True(viewModel.IsRunning);
        Assert.Equal(30, viewModel.Progress);
    }

    [Fact]
    public async Task The_end_shows_the_counts_reloads_the_meetings_and_lists_the_errors()
    {
        var viewModel = Create();
        viewModel.OnProgress(new MigrationProgressEvent(null, 0, 2, "a", false));
        _client.Migration = Summary("done", done: 2, total: 2, imported: 1, errors: Bad);

        await viewModel.OnDoneAsync(new MigrationDoneEvent(null, "done", 1, 1, 1));

        Assert.False(viewModel.IsRunning);
        Assert.True(viewModel.IsFinished);
        Assert.True(viewModel.IsVisible);
        Assert.Equal(_localization.Format("MigrationDone", 1, 1), viewModel.Text);
        Assert.True(viewModel.HasErrors);
        Assert.Equal([Bad], viewModel.Errors);
        Assert.Equal(1, _reloads);

        viewModel.ShowErrorsCommand.Execute(null);
        Assert.True(viewModel.ErrorsOpen);
        viewModel.CloseErrorsCommand.Execute(null);
        Assert.False(viewModel.ErrorsOpen);
        viewModel.ShowErrorsCommand.Execute(null);
        viewModel.DismissCommand.Execute(null);
        Assert.False(viewModel.IsVisible);
        Assert.False(viewModel.ErrorsOpen);
    }

    [Fact]
    public async Task An_import_seen_running_shows_its_end_even_when_nothing_was_imported()
    {
        var viewModel = Create();
        viewModel.OnProgress(new MigrationProgressEvent(null, 0, 1, "a", false));
        _client.Migration = Summary("done", done: 1, total: 1, errors: Bad);

        await viewModel.OnDoneAsync(new MigrationDoneEvent(null, "done", 0, 1, 1));

        Assert.True(viewModel.IsFinished);
        Assert.Equal(0, _reloads); // nothing new in the list
    }

    [Fact]
    public async Task A_full_disk_shows_the_engine_message()
    {
        _client.Migration = Summary("no_space", message: "Not enough space");
        var viewModel = Create();

        await viewModel.RefreshAsync();

        Assert.True(viewModel.IsFinished);
        Assert.Equal("Not enough space", viewModel.Text);
    }

    [Theory]
    [InlineData("failed", null)]
    [InlineData("no_space", null)]
    public async Task A_failure_shows_the_generic_message(string state, string? message)
    {
        _client.Migration = Summary(state, message: message);
        var viewModel = Create();

        await viewModel.RefreshAsync();

        Assert.Equal(_localization["MigrationFailed"], viewModel.Text);
    }

    [Fact]
    public async Task An_unreachable_engine_changes_nothing()
    {
        _client.Migration = Summary("running", done: 1, total: 2);
        var viewModel = Create();
        await viewModel.RefreshAsync();
        _client.MigrationError = new EngineUnavailableException("down", new HttpRequestException());

        await viewModel.RefreshAsync();

        Assert.True(viewModel.IsRunning);
    }

    [Fact]
    public void A_lost_connection_hides_the_progress()
    {
        var viewModel = Create();
        viewModel.OnProgress(new MigrationProgressEvent(null, 1, 2, "a", false));

        viewModel.OnConnectionLost();

        Assert.False(viewModel.IsVisible);
    }

    [Fact]
    public async Task Texts_follow_the_language()
    {
        var viewModel = Create();
        viewModel.RefreshTexts(); // nothing shown yet: no text
        Assert.Equal("", viewModel.Text);
        viewModel.OnProgress(new MigrationProgressEvent(null, 1, 2, "a", false));

        _localization.SetLanguage("pt-BR");
        viewModel.RefreshTexts();

        Assert.Equal(_localization.Format("MigrationProgress", 1, 2), viewModel.Text);
        Assert.StartsWith("Importando", viewModel.Text);
        await Task.CompletedTask;
    }
}
