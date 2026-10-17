using VozAta.Desktop.Services;
using VozAta.Desktop.Tests.Fakes;
using VozAta.Desktop.ViewModels;

namespace VozAta.Desktop.Tests;

/// <summary>The glossary editor (phase 19): load, add, remove, import; every change is saved.</summary>
public sealed class VocabularyViewModelTests
{
    private readonly FakeEngineClient _client = new();
    private readonly LocalizationService _localization = new();

    private VocabularyViewModel Create() => new(_client, _localization);

    [Fact]
    public async Task Load_shows_the_engine_glossary()
    {
        _client.VocabularyTerms.AddRange(["Avalonia", "N5 Sensors"]);
        var viewModel = Create();

        await viewModel.LoadAsync();

        Assert.Equal(["Avalonia", "N5 Sensors"], viewModel.Terms);
        Assert.False(viewModel.IsEmpty);
        Assert.Null(viewModel.Error);
    }

    [Fact]
    public async Task An_empty_glossary_is_reported_as_empty()
    {
        var viewModel = Create();

        await viewModel.LoadAsync();

        Assert.True(viewModel.IsEmpty);
    }

    [Fact]
    public async Task Add_saves_the_new_term_and_clears_the_box()
    {
        _client.VocabularyTerms.Add("Avalonia");
        var viewModel = Create();
        await viewModel.LoadAsync();
        viewModel.NewTerm = "  Jéssica ";

        await viewModel.AddCommand.ExecuteAsync(null);

        Assert.Equal(["Avalonia", "Jéssica"], _client.VocabularyUpdates.Single());
        Assert.Equal(["Avalonia", "Jéssica"], viewModel.Terms);
        Assert.Equal("", viewModel.NewTerm);
        Assert.Equal("Vocabulary saved.", viewModel.Message);
    }

    [Fact]
    public void Add_is_disabled_for_a_blank_term()
    {
        var viewModel = Create();

        viewModel.NewTerm = " , ";

        Assert.False(viewModel.AddCommand.CanExecute(null));
    }

    [Fact]
    public async Task Remove_saves_the_list_without_the_term()
    {
        _client.VocabularyTerms.AddRange(["Avalonia", "Jéssica", "N5"]);
        var viewModel = Create();
        await viewModel.LoadAsync();

        await viewModel.RemoveCommand.ExecuteAsync("Jéssica");

        Assert.Equal(["Avalonia", "N5"], _client.VocabularyUpdates.Single());
        Assert.Equal(["Avalonia", "N5"], viewModel.Terms);
        Assert.False(viewModel.RemoveCommand.CanExecute(null));
    }

    [Fact]
    public async Task Import_adds_every_term_of_the_pasted_text_once()
    {
        _client.VocabularyTerms.Add("Avalonia");
        var viewModel = Create();
        await viewModel.LoadAsync();
        viewModel.ImportText = "Kubernetes, Grafana\r\navalonia\n\nPrometheus; Grafana";

        await viewModel.ImportCommand.ExecuteAsync(null);

        Assert.Equal(["Avalonia", "Kubernetes", "Grafana", "Prometheus"], viewModel.Terms);
        Assert.Equal("", viewModel.ImportText);
    }

    [Fact]
    public void Import_is_disabled_without_terms()
    {
        var viewModel = Create();

        viewModel.ImportText = "\n , \n";

        Assert.False(viewModel.ImportCommand.CanExecute(null));
    }

    [Fact]
    public async Task A_failed_save_keeps_the_typed_term_and_shows_the_error()
    {
        var viewModel = Create();
        await viewModel.LoadAsync();
        _client.VocabularyError = FakeEngineClient.ApiError("vocabulary_failed", "The vocabulary file could not be saved.");
        viewModel.NewTerm = "Jéssica";

        await viewModel.AddCommand.ExecuteAsync(null);

        Assert.Equal("The vocabulary file could not be saved.", viewModel.Error);
        Assert.Equal("Jéssica", viewModel.NewTerm);
        Assert.Empty(viewModel.Terms);
        Assert.False(viewModel.IsBusy);
    }

    [Fact]
    public async Task A_load_without_the_engine_shows_it_is_unavailable()
    {
        _client.VocabularyError = new VozAta.Client.EngineUnavailableException("refused", new HttpRequestException("refused"));
        var viewModel = Create();

        await viewModel.LoadAsync();

        Assert.Equal(_localization["EngineUnavailable"], viewModel.Error);
    }

    [Theory]
    [InlineData(null, new string[0])]
    [InlineData("", new string[0])]
    [InlineData("Avalonia", new[] { "Avalonia" })]
    [InlineData(" a , b\nB ;c ", new[] { "a", "b", "c" })]
    public void Parse_terms_splits_trims_and_deduplicates(string? text, string[] expected)
    {
        Assert.Equal(expected, VocabularyViewModel.ParseTerms(text));
    }
}
