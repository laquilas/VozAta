using System.Net;
using System.Text.Json;
using VozAta.Client;

namespace VozAta.Desktop.Tests.Fakes;

/// <summary>Scriptable engine: canned answers, recorded calls, optional failures.</summary>
internal sealed class FakeEngineClient : IEngineClient
{
    public List<string> Calls { get; } = [];

    public List<StartSessionRequest> StartRequests { get; } = [];

    /// <summary>Health checks fail with "unavailable" this many times before succeeding.</summary>
    public int UnavailableHealthChecks { get; set; }

    public Exception? StartError { get; set; }

    public Exception? StopError { get; set; }

    public EngineHealth Health { get; set; } = new(
        "ok",
        "0.1.0",
        new GpuStatus(true, "RTX 3050", 6144),
        new SttStatus("faster_whisper", "large-v3", "auto"),
        new LlmStatus("ollama", "qwen2.5:7b", true));

    public Dictionary<string, object?> SettingValues { get; } = new()
    {
        ["APP_LANGUAGE"] = "en",
        ["TRANSCRIPTION_LANGUAGE"] = "pt",
    };

    public Task<EngineHealth> GetHealthAsync(CancellationToken cancellationToken = default)
    {
        Calls.Add("health");
        if (UnavailableHealthChecks > 0)
        {
            UnavailableHealthChecks--;
            throw new EngineUnavailableException("refused", new HttpRequestException("refused"));
        }

        return Task.FromResult(Health);
    }

    public DeviceList Devices { get; set; } = new([], [], null, null);

    public Exception? DevicesError { get; set; }

    public Task<DeviceList> GetDevicesAsync(CancellationToken cancellationToken = default)
    {
        Calls.Add("devices");
        return DevicesError is null ? Task.FromResult(Devices) : Task.FromException<DeviceList>(DevicesError);
    }

    public Task<SessionSummary> StartSessionAsync(
        StartSessionRequest request, CancellationToken cancellationToken = default)
    {
        Calls.Add("start");
        StartRequests.Add(request);
        return StartError is null ? Task.FromResult(Summary("recording")) : Task.FromException<SessionSummary>(StartError);
    }

    public Exception? PauseError { get; set; }

    public Task<SessionSummary> PauseSessionAsync(CancellationToken cancellationToken = default)
    {
        Calls.Add("pause");
        return PauseError is null ? Task.FromResult(Summary("paused")) : Task.FromException<SessionSummary>(PauseError);
    }

    public Task<SessionSummary> ResumeSessionAsync(CancellationToken cancellationToken = default)
    {
        Calls.Add("resume");
        return Task.FromResult(Summary("recording"));
    }

    public Task<SessionSummary> StopSessionAsync(CancellationToken cancellationToken = default)
    {
        Calls.Add("stop");
        return StopError is null ? Task.FromResult(Summary("finalizing")) : Task.FromException<SessionSummary>(StopError);
    }

    /// <summary>Every session, newest first (paged by <see cref="ListSessionsAsync"/>).</summary>
    public List<SessionSummary> Sessions { get; } = [];

    public Dictionary<string, SessionDetail> Details { get; } = [];

    public Dictionary<string, Transcript> Transcripts { get; } = [];

    /// <summary>Minutes per session; a missing entry answers 404 <c>minutes_not_found</c>.</summary>
    public Dictionary<string, string> MinutesText { get; } = [];

    public List<(int Limit, int Offset)> ListRequests { get; } = [];

    public List<string> Regenerated { get; } = [];

    public Exception? ListError { get; set; }

    public Exception? DetailError { get; set; }

    public Exception? RegenerateError { get; set; }

    public Task<SessionPage> ListSessionsAsync(
        int limit = 50, int offset = 0, CancellationToken cancellationToken = default)
    {
        ListRequests.Add((limit, offset));
        return ListError is null
            ? Task.FromResult(new SessionPage([.. Sessions.Skip(offset).Take(limit)], Sessions.Count))
            : Task.FromException<SessionPage>(ListError);
    }

    public Task<SessionDetail> GetSessionAsync(string id, CancellationToken cancellationToken = default) =>
        DetailError is null ? Task.FromResult(Details[id]) : Task.FromException<SessionDetail>(DetailError);

    public Task<Transcript> GetTranscriptAsync(string id, CancellationToken cancellationToken = default) =>
        Task.FromResult(Transcripts.GetValueOrDefault(id) ?? new Transcript("raw", []));

    public Task<Minutes> GetMinutesAsync(string id, CancellationToken cancellationToken = default) =>
        MinutesText.TryGetValue(id, out var markdown)
            ? Task.FromResult(new Minutes(markdown))
            : Task.FromException<Minutes>(new EngineApiException(HttpStatusCode.NotFound, "minutes_not_found", "No minutes yet."));

    /// <summary>Every transcript save (phase 21), in order.</summary>
    public List<(string Id, IReadOnlyList<SegmentTextEdit> Segments)> TranscriptUpdates { get; } = [];

    public List<string> TranscriptReverts { get; } = [];

    public Exception? TranscriptUpdateError { get; set; }

    public Exception? TranscriptRevertError { get; set; }

    private readonly Dictionary<string, Transcript> _originalTranscripts = [];

    /// <summary>Applies the texts like the engine: changed segments become edited, without words.</summary>
    public Task<TranscriptEditResult> UpdateTranscriptAsync(
        string id, IReadOnlyList<SegmentTextEdit> segments, CancellationToken cancellationToken = default)
    {
        TranscriptUpdates.Add((id, segments));
        if (TranscriptUpdateError is not null)
        {
            return Task.FromException<TranscriptEditResult>(TranscriptUpdateError);
        }

        var current = Transcripts.GetValueOrDefault(id) ?? new Transcript("raw", []);
        _originalTranscripts.TryAdd(id, current);
        var texts = segments.ToDictionary(segment => segment.SegmentId, segment => segment.Text);
        Transcripts[id] = new Transcript("edited", [.. current.Segments.Select(segment =>
            texts.TryGetValue(segment.SegmentId, out var text) && text != segment.Text
                ? segment with { Text = text, Edited = true, Words = [] }
                : segment)]);
        return Task.FromResult(new TranscriptEditResult("edited"));
    }

    public Task RevertTranscriptAsync(string id, CancellationToken cancellationToken = default)
    {
        TranscriptReverts.Add(id);
        if (TranscriptRevertError is not null)
        {
            return Task.FromException(TranscriptRevertError);
        }

        if (_originalTranscripts.Remove(id, out var original))
        {
            Transcripts[id] = original;
        }

        return Task.CompletedTask;
    }

    public List<(string Id, string Format)> Exports { get; } = [];

    public Exception? ExportError { get; set; }

    public Task<ExportedFile> ExportSessionAsync(string id, string format, CancellationToken cancellationToken = default)
    {
        Exports.Add((id, format));
        return ExportError is null
            ? Task.FromResult(new ExportedFile($"{id}-minutes.{format}", [1, 2, 3]))
            : Task.FromException<ExportedFile>(ExportError);
    }

    /// <summary>The template of each regeneration, in the same order as <see cref="Regenerated"/>.</summary>
    public List<string?> RegeneratedTemplates { get; } = [];

    public Task RegenerateMinutesAsync(string id, string? templateId = null, CancellationToken cancellationToken = default)
    {
        Regenerated.Add(id);
        RegeneratedTemplates.Add(templateId);
        return RegenerateError is null ? Task.CompletedTask : Task.FromException(RegenerateError);
    }

    /// <summary>Every <c>POST /sessions/{id}/recover</c>, in order (phase 17).</summary>
    public List<string> Recovered { get; } = [];

    public Exception? RecoverError { get; set; }

    public Task RecoverSessionAsync(string id, CancellationToken cancellationToken = default)
    {
        Recovered.Add(id);
        return RecoverError is null ? Task.CompletedTask : Task.FromException(RecoverError);
    }

    /// <summary>Speakers of each session (phase 16); <see cref="UpdateSpeakersAsync"/> applies names to them.</summary>
    public Dictionary<string, Dictionary<string, SpeakerInfo>> Speakers { get; } = [];

    /// <summary>Every <c>PUT /sessions/{id}/speakers</c> payload, in order.</summary>
    public List<(string Id, IReadOnlyDictionary<string, string?> Names)> SpeakerUpdates { get; } = [];

    public Exception? SpeakersError { get; set; }

    public Exception? UpdateSpeakersError { get; set; }

    public Task<SessionSpeakers> GetSpeakersAsync(string id, CancellationToken cancellationToken = default) =>
        SpeakersError is null
            ? Task.FromResult(new SessionSpeakers(new Dictionary<string, SpeakerInfo>(Speakers.GetValueOrDefault(id) ?? [])))
            : Task.FromException<SessionSpeakers>(SpeakersError);

    public Task<SessionSpeakers> UpdateSpeakersAsync(
        string id, IReadOnlyDictionary<string, string?> names, CancellationToken cancellationToken = default)
    {
        SpeakerUpdates.Add((id, names));
        if (UpdateSpeakersError is not null)
        {
            return Task.FromException<SessionSpeakers>(UpdateSpeakersError);
        }

        var speakers = Speakers.TryGetValue(id, out var known) ? known : Speakers[id] = [];
        foreach (var (speakerId, name) in names)
        {
            var label = speakers.TryGetValue(speakerId, out var info) ? info.DefaultLabel : speakerId;
            speakers[speakerId] = new SpeakerInfo(string.IsNullOrWhiteSpace(name) ? null : name.Trim(), label);
        }

        return GetSpeakersAsync(id, cancellationToken);
    }

    public List<MinutesTemplate> Templates { get; } =
    [
        new("general", "General meeting"),
        new("daily", "Daily stand-up"),
        new("client", "Client meeting"),
    ];

    public Exception? TemplatesError { get; set; }

    public Task<IReadOnlyList<MinutesTemplate>> GetTemplatesAsync(CancellationToken cancellationToken = default)
    {
        Calls.Add("templates");
        return TemplatesError is null
            ? Task.FromResult<IReadOnlyList<MinutesTemplate>>([.. Templates])
            : Task.FromException<IReadOnlyList<MinutesTemplate>>(TemplatesError);
    }

    public Exception? SettingsError { get; set; }

    public Task<EngineSettings> GetSettingsAsync(CancellationToken cancellationToken = default)
    {
        Calls.Add("settings");
        if (SettingsError is not null)
        {
            return Task.FromException<EngineSettings>(SettingsError);
        }

        var values = SettingValues.ToDictionary(
            pair => pair.Key, pair => JsonSerializer.SerializeToElement(pair.Value));
        return Task.FromResult(new EngineSettings(values, Schema));
    }

    public List<IReadOnlyDictionary<string, object?>> Updates { get; } = [];

    public List<SettingSchema> Schema { get; } = [];

    /// <summary>Keys the next update reports as needing a restart.</summary>
    public List<string> RestartKeys { get; } = [];

    public Exception? UpdateError { get; set; }

    public Task<SettingsUpdateResult> UpdateSettingsAsync(
        IReadOnlyDictionary<string, object?> values, CancellationToken cancellationToken = default)
    {
        Calls.Add("update-settings");
        Updates.Add(values);
        if (UpdateError is not null)
        {
            return Task.FromException<SettingsUpdateResult>(UpdateError);
        }

        foreach (var (key, value) in values)
        {
            SettingValues[key] = value;
        }

        var saved = SettingValues.ToDictionary(pair => pair.Key, pair => JsonSerializer.SerializeToElement(pair.Value));
        return Task.FromResult(new SettingsUpdateResult(saved, [.. RestartKeys.Where(values.ContainsKey)]));
    }

    /// <summary>Hits answered by <see cref="SearchAsync"/> (phase 22), whatever the query.</summary>
    public List<SearchHit> SearchHits { get; } = [];

    public List<string> Searches { get; } = [];

    public Exception? SearchError { get; set; }

    /// <summary>When set, searches wait for it (tests cancel a search in flight).</summary>
    public TaskCompletionSource? SearchGate { get; set; }

    public async Task<SearchResults> SearchAsync(
        string query, int limit = 50, CancellationToken cancellationToken = default)
    {
        Searches.Add(query);
        if (SearchGate is not null)
        {
            await SearchGate.Task.WaitAsync(cancellationToken);
        }

        cancellationToken.ThrowIfCancellationRequested();
        return SearchError is null ? new SearchResults([.. SearchHits.Take(limit)]) : throw SearchError;
    }

    /// <summary>The glossary (phase 19); updates replace it with trimmed, deduplicated terms.</summary>
    public List<string> VocabularyTerms { get; } = [];

    public List<IReadOnlyList<string>> VocabularyUpdates { get; } = [];

    public Exception? VocabularyError { get; set; }

    public Task<IReadOnlyList<string>> GetVocabularyAsync(CancellationToken cancellationToken = default)
    {
        Calls.Add("vocabulary");
        return VocabularyError is null
            ? Task.FromResult<IReadOnlyList<string>>([.. VocabularyTerms])
            : Task.FromException<IReadOnlyList<string>>(VocabularyError);
    }

    public Task<IReadOnlyList<string>> UpdateVocabularyAsync(
        IReadOnlyList<string> terms, CancellationToken cancellationToken = default)
    {
        Calls.Add("update-vocabulary");
        VocabularyUpdates.Add(terms);
        if (VocabularyError is not null)
        {
            return Task.FromException<IReadOnlyList<string>>(VocabularyError);
        }

        VocabularyTerms.Clear();
        VocabularyTerms.AddRange(terms
            .Select(term => term.Trim())
            .Where(term => term.Length > 0)
            .DistinctBy(term => term.ToUpperInvariant()));
        return Task.FromResult<IReadOnlyList<string>>([.. VocabularyTerms]);
    }

    /// <summary>Every <c>POST /ask</c> (phase 24): question and scope.</summary>
    public List<(string Question, string? SessionId)> Questions { get; } = [];

    /// <summary>The id answered by the next <see cref="AskAsync"/>.</summary>
    public string NextAnswerId { get; set; } = "answer-1";

    public Exception? AskError { get; set; }

    /// <summary>When set, <see cref="AskAsync"/> waits for it (events may arrive before its answer).</summary>
    public TaskCompletionSource? AskGate { get; set; }

    public async Task<AskAccepted> AskAsync(
        string question, string? sessionId = null, CancellationToken cancellationToken = default)
    {
        Questions.Add((question, sessionId));
        if (AskGate is not null)
        {
            await AskGate.Task.WaitAsync(cancellationToken);
        }

        return AskError is null ? new AskAccepted(NextAnswerId) : throw AskError;
    }

    public static EngineApiException ApiError(string code, string message) =>
        new(HttpStatusCode.Conflict, code, message);

    private static SessionSummary Summary(string status) =>
        new("20261016_090000", status, DateTimeOffset.Now, null, 0, "pt", false);
}
