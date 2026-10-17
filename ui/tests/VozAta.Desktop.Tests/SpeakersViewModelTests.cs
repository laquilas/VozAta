using VozAta.Client;
using VozAta.Desktop.Services;
using VozAta.Desktop.Tests.Fakes;
using VozAta.Desktop.ViewModels;

namespace VozAta.Desktop.Tests;

public sealed class SpeakersViewModelTests
{
    private const string Id = "20261016_090000";

    private readonly FakeEngineClient _client = new();
    private readonly LocalizationService _localization = new();
    private readonly List<string> _calls = [];
    private bool _hasMinutes;

    private static readonly IReadOnlyList<Segment> Segments =
    [
        Line("mic-000001", "mic", "mic", "Me", "Good morning."),
        Line("system-000001", "system:2", "Bruno", "Hi, Bruno here."),
        Line("system-000002", "system:1", "User 1", "Hello everyone."),
        Line("system-000003", "system:2", "Bruno", "Second line."),
        Line("system-000004", "system:2", "Bruno", "Third line is not a hint."),
    ];

    public SpeakersViewModelTests()
    {
        _client.Speakers[Id] = new()
        {
            ["mic"] = new SpeakerInfo(null, "Me"),
            ["system:1"] = new SpeakerInfo(null, "User 1"),
            ["system:2"] = new SpeakerInfo("Bruno", "User 2"),
        };
    }

    private static Segment Line(string id, string speakerId, string label, string text) =>
        Line(id, "system", speakerId, label, text);

    private static Segment Line(string id, string channel, string speakerId, string label, string text) =>
        new(id, channel, speakerId, label, 0, 1, text, false, []);

    private SpeakersViewModel Create() => new(
        _client,
        _localization,
        Id,
        reloadTranscript: _ =>
        {
            _calls.Add("reload");
            return Task.CompletedTask;
        },
        hasMinutes: () => _hasMinutes,
        regenerateMinutes: () =>
        {
            _calls.Add("regenerate");
            return Task.CompletedTask;
        });

    [Fact]
    public async Task Rows_are_built_from_transcript_speakers_in_order_with_two_snippets_as_hint()
    {
        var speakers = Create();

        await speakers.LoadAsync(Segments);

        Assert.Equal(["mic", "system:2", "system:1"], speakers.Rows.Select(row => row.SpeakerId));
        var bruno = speakers.Rows[1];
        Assert.Equal("User 2", bruno.DefaultLabel);
        Assert.Equal("Bruno", bruno.Name);
        Assert.Equal("“Hi, Bruno here.” “Second line.”", bruno.Hint);
        Assert.Equal("", speakers.Rows[0].Name);
        Assert.True(speakers.HasRows);
        Assert.True(speakers.SaveCommand.CanExecute(null));
    }

    [Fact]
    public async Task Long_snippets_are_shortened_and_unknown_speakers_fall_back_to_the_transcript_label()
    {
        _client.Speakers.Clear();
        var speakers = Create();

        await speakers.LoadAsync([Line("system-000001", "system", "Others", new string('a', 120))]);

        var row = Assert.Single(speakers.Rows);
        Assert.Equal("Others", row.DefaultLabel);
        Assert.Equal($"“{new string('a', 80)}…”", row.Hint);
    }

    [Fact]
    public async Task Saving_sends_every_row_trimmed_with_empty_names_as_null_then_reloads_the_transcript()
    {
        var speakers = Create();
        await speakers.LoadAsync(Segments);
        speakers.Rows[0].Name = "  Ana ";
        speakers.Rows[1].Name = "   ";
        speakers.Rows[2].Name = "Carla";

        await speakers.SaveCommand.ExecuteAsync(null);

        var (id, names) = Assert.Single(_client.SpeakerUpdates);
        Assert.Equal(Id, id);
        Assert.Equal(
            new Dictionary<string, string?> { ["mic"] = "Ana", ["system:2"] = null, ["system:1"] = "Carla" },
            names);
        Assert.Equal(["reload"], _calls);
        Assert.Equal(_localization["SpeakersSaved"], speakers.Message);
        Assert.False(speakers.OfferRegenerate);  // no minutes yet
        Assert.False(speakers.IsSaving);
    }

    [Fact]
    public async Task The_regenerate_prompt_is_shown_only_when_minutes_exist()
    {
        _hasMinutes = true;
        var speakers = Create();
        await speakers.LoadAsync(Segments);
        Assert.False(speakers.OfferRegenerate);  // not before a save

        await speakers.SaveCommand.ExecuteAsync(null);

        Assert.True(speakers.OfferRegenerate);
        Assert.Null(speakers.Message);

        await speakers.RegenerateCommand.ExecuteAsync(null);

        Assert.Equal(["reload", "regenerate"], _calls);
        Assert.False(speakers.OfferRegenerate);
    }

    [Fact]
    public async Task The_regenerate_prompt_can_be_dismissed()
    {
        _hasMinutes = true;
        var speakers = Create();
        await speakers.LoadAsync(Segments);
        await speakers.SaveCommand.ExecuteAsync(null);

        speakers.DismissRegenerateCommand.Execute(null);

        Assert.False(speakers.OfferRegenerate);
        Assert.DoesNotContain("regenerate", _calls);
    }

    [Fact]
    public async Task Save_errors_are_shown_and_nothing_is_reloaded()
    {
        _hasMinutes = true;
        _client.UpdateSpeakersError = FakeEngineClient.ApiError("unknown_speaker", "Unknown speaker.");
        var speakers = Create();
        await speakers.LoadAsync(Segments);

        await speakers.SaveCommand.ExecuteAsync(null);

        Assert.Equal("Unknown speaker.", speakers.Error);
        Assert.Empty(_calls);
        Assert.False(speakers.OfferRegenerate);
        Assert.False(speakers.IsSaving);
    }

    [Fact]
    public async Task Load_errors_are_shown_and_leave_no_rows()
    {
        _client.SpeakersError = new EngineUnavailableException("refused", new HttpRequestException());
        var speakers = Create();

        await speakers.LoadAsync(Segments);

        Assert.Equal(_localization["EngineUnavailable"], speakers.Error);
        Assert.Empty(speakers.Rows);
        Assert.False(speakers.HasRows);
        Assert.False(speakers.SaveCommand.CanExecute(null));
    }

    [Fact]
    public async Task An_empty_transcript_has_no_rows_and_skips_the_engine()
    {
        _client.SpeakersError = new InvalidOperationException("must not be called");
        var speakers = Create();

        await speakers.LoadAsync([]);

        Assert.Empty(speakers.Rows);
        Assert.Null(speakers.Error);
    }

    [Fact]
    public async Task The_session_detail_loads_its_speakers_and_reloads_after_a_save()
    {
        _client.Details[Id] = new SessionDetail(Id, "done", null, null, 75, "pt", true, [], @"C:\VozAta\" + Id);
        _client.Transcripts[Id] = new Transcript("diarized", Segments);
        _client.MinutesText[Id] = "## Summary";
        var summary = new SessionSummary(Id, "done", null, null, 75, "pt", true);
        var detail = new SessionDetailViewModel(_client, new FakeShell(), _localization, new FakeFileSaver(), summary);

        await detail.LoadAsync();
        detail.Speakers.Rows[2].Name = "Carla";
        _client.Transcripts[Id] = new Transcript("diarized", [Line("system-000002", "system:1", "Carla", "Hello everyone.")]);
        await detail.Speakers.SaveCommand.ExecuteAsync(null);

        Assert.Equal("Carla", Assert.Single(detail.Lines).Label);
        Assert.Equal(["system:1"], detail.Speakers.Rows.Select(row => row.SpeakerId));
        Assert.True(detail.Speakers.OfferRegenerate);

        await detail.Speakers.RegenerateCommand.ExecuteAsync(null);

        Assert.Equal([Id], _client.Regenerated);
    }

    [Fact]
    public async Task A_live_session_does_not_load_speakers()
    {
        _client.Details[Id] = new SessionDetail(Id, "recording", null, null, 5, "pt", false, [], @"C:\VozAta\" + Id);
        _client.Transcripts[Id] = new Transcript("raw", Segments);
        _client.SpeakersError = new InvalidOperationException("must not be called");
        var summary = new SessionSummary(Id, "recording", null, null, 5, "pt", false);
        var detail = new SessionDetailViewModel(_client, new FakeShell(), _localization, new FakeFileSaver(), summary);

        await detail.LoadAsync();

        Assert.Empty(detail.Speakers.Rows);
        Assert.Null(detail.Speakers.Error);
    }
}
