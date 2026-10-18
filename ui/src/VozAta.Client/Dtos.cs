using System.Text.Json;
using System.Text.Json.Serialization;

namespace VozAta.Client;

// Shapes of docs/roadmap/api-contract.md (rows tagged 06). JSON uses snake_case (EngineJson).

public sealed record GpuStatus(bool Available, string? Name, int? VramTotalMb);

public sealed record SttStatus(string Provider, string Model, string Device);

public sealed record LlmStatus(string Provider, string Model, bool Reachable);

public sealed record EngineHealth(
    string Engine,
    string Version,
    GpuStatus Gpu,
    SttStatus Stt,
    LlmStatus Llm);

public sealed record AudioDevice(int Id, string Name, int SampleRate, int Channels)
{
    /// <summary>The name: what pickers and screen readers show.</summary>
    public override string ToString() => Name;
}

public sealed record DeviceList(
    IReadOnlyList<AudioDevice> Inputs,
    IReadOnlyList<AudioDevice> Loopbacks,
    int? DefaultInputId,
    int? DefaultLoopbackId);

public sealed record StartSessionRequest(
    int? MicDeviceId = null,
    int? SystemDeviceId = null,
    string? Language = null,
    string? Template = null,
    [property: JsonIgnore(Condition = JsonIgnoreCondition.WhenWritingNull)]
    IReadOnlyList<string>? Vocabulary = null,
    [property: JsonIgnore(Condition = JsonIgnoreCondition.WhenWritingNull)]
    string? TranslateTo = null,
    [property: JsonIgnore(Condition = JsonIgnoreCondition.WhenWritingNull)]
    string? Title = null);

/// <summary><c>GET|PUT /vocabulary</c> (phase 19): the glossary terms, one per entry.</summary>
public sealed record VocabularyTerms(IReadOnlyList<string> Terms);

/// <summary>A minutes template (phase 20): stable id and name in the engine's app language.</summary>
public sealed record MinutesTemplate(string Id, string Name)
{
    /// <summary>The name: what pickers and screen readers show.</summary>
    public override string ToString() => Name;
}

public sealed record SessionSummary(
    string Id,
    string Status,
    DateTimeOffset? StartedAt,
    DateTimeOffset? EndedAt,
    double? DurationSeconds,
    string? Language,
    bool HasMinutes,
    string? Title = null);

public sealed record SessionPage(IReadOnlyList<SessionSummary> Items, int Total);

public sealed record SessionDetail(
    string Id,
    string Status,
    DateTimeOffset? StartedAt,
    DateTimeOffset? EndedAt,
    double? DurationSeconds,
    string? Language,
    bool HasMinutes,
    IReadOnlyList<string>? Files,
    string? Folder,
    IReadOnlyDictionary<string, double>? Audio = null)
{
    /// <summary>Every other `session.json` field (devices, pauses, settings...).</summary>
    [JsonExtensionData]
    public IDictionary<string, JsonElement>? Metadata { get; init; }
}

public sealed record Word(string Text, double Start, double End, double Probability);

/// <summary>A segment translated live (phase 29): the target language and the text.</summary>
public sealed record SegmentTranslation(string Language, string Text);

public sealed record Segment(
    string SegmentId,
    string Channel,
    string SpeakerId,
    string Label,
    double Start,
    double End,
    string Text,
    bool Edited,
    IReadOnlyList<Word> Words,
    SegmentTranslation? Translation = null);

public sealed record Transcript(string Source, IReadOnlyList<Segment> Segments);

/// <summary>A corrected segment text for <c>PUT /sessions/{id}/transcript</c> (phase 21).</summary>
public sealed record SegmentTextEdit(string SegmentId, string Text);

/// <summary>The <c>PUT /sessions/{id}/transcript</c> answer: the transcript source is now <c>edited</c>.</summary>
public sealed record TranscriptEditResult(string Source);

public sealed record Minutes(string Markdown);

/// <summary>A speaker of one session (phase 16): the given name (null = unset) and the label without it.</summary>
public sealed record SpeakerInfo(string? Name, string DefaultLabel);

/// <summary><c>GET</c>/<c>PUT /sessions/{id}/speakers</c>: every transcript speaker by id.</summary>
public sealed record SessionSpeakers(IReadOnlyDictionary<string, SpeakerInfo> Speakers);

/// <summary>A downloaded export: the engine's file name and the bytes.</summary>
public sealed record ExportedFile(string FileName, byte[] Content);

/// <summary>One <c>GET /search</c> match (phase 22); <see cref="Snippet"/> wraps matches in markers.</summary>
public sealed record SearchHit(
    string SessionId,
    string SegmentId,
    double Start,
    string SpeakerId,
    string Label,
    string Snippet)
{
    /// <summary>Starts a matched term in <see cref="Snippet"/>.</summary>
    public const char MatchStart = '\u0002';

    /// <summary>Ends a matched term in <see cref="Snippet"/>.</summary>
    public const char MatchEnd = '\u0003';
}

public sealed record SearchResults(IReadOnlyList<SearchHit> Hits);

public sealed record SettingSchema(
    string Key,
    string Type,
    JsonElement Default,
    IReadOnlyList<string>? Choices,
    bool Secret,
    string Group = "general",
    string Applies = "next_session")
{
    /// <summary>Read once when the engine starts: saving it needs an engine restart.</summary>
    public bool NeedsRestart => Applies == "restart";
}

/// <summary><c>PUT /settings</c> answer: the saved values and the keys that need a restart.</summary>
public sealed record SettingsUpdateResult(
    IReadOnlyDictionary<string, JsonElement> Values,
    IReadOnlyList<string> RestartRequired);

public sealed record EngineSettings(
    IReadOnlyDictionary<string, JsonElement> Values,
    IReadOnlyList<SettingSchema> Schema)
{
    /// <summary>A setting as text (null when unset or not a string/number/bool).</summary>
    public string? GetString(string key) =>
        Values.TryGetValue(key, out var value) ? value.ValueKind switch
        {
            JsonValueKind.String => value.GetString(),
            JsonValueKind.Number or JsonValueKind.True or JsonValueKind.False => value.GetRawText(),
            _ => null,
        } : null;
}
