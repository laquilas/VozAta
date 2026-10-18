using VozAta.Client;
using VozAta.Desktop.Services;
using VozAta.Desktop.Tests.Fakes;
using VozAta.Desktop.ViewModels;

namespace VozAta.Desktop.Tests;

/// <summary>Custom vocabulary (phase 19): meeting terms on the Start screen, glossary loaded at start-up.</summary>
public sealed class SessionTermsTests
{
    private readonly FakeEngineClient _client = new();
    private readonly FakeEngineEvents _events = new();

    private async Task<MainViewModel> ReadyAsync()
    {
        var viewModel = new MainViewModel(
            _client, _events, new FakeEngineProcess(), new ImmediateDispatcher(), new LocalizationService(), new FakeDialogs(),
            new FakePreferences(), new FakeClock(), new FakeTimer(), new FakeShell(), new FakeFileSaver(), new FakeThemeService());
        await viewModel.InitializeAsync();
        _events.Send(new ConnectionChangedEvent(true));
        for (var i = 0; i < 200 && viewModel.EngineStatus != EngineStatus.Connected; i++)
        {
            await Task.Delay(5);
        }

        return viewModel;
    }

    [Fact]
    public async Task The_meeting_terms_are_sent_on_start()
    {
        var viewModel = await ReadyAsync();
        viewModel.Recorder.SessionTerms = "Jéssica, N5 Sensors\nKubernetes\n jéssica ";

        await viewModel.Recorder.StartCommand.ExecuteAsync(null);

        Assert.Equal(["Jéssica", "N5 Sensors", "Kubernetes"], _client.StartRequests.Single().Vocabulary);
    }

    [Fact]
    public async Task Without_meeting_terms_no_vocabulary_is_sent()
    {
        var viewModel = await ReadyAsync();
        viewModel.Recorder.SessionTerms = " ,\n ";

        await viewModel.Recorder.StartCommand.ExecuteAsync(null);

        Assert.Null(_client.StartRequests.Single().Vocabulary);
    }

    [Fact]
    public async Task The_glossary_is_loaded_with_the_settings()
    {
        _client.VocabularyTerms.Add("Avalonia");

        var viewModel = await ReadyAsync();

        Assert.Equal(["Avalonia"], viewModel.Vocabulary.Terms);
        Assert.Contains("vocabulary", _client.Calls);
    }
}
