using System.Globalization;
using System.Net;
using System.Net.Http.Headers;
using System.Net.Http.Json;
using System.Text.Json;

namespace VozAta.Client;

/// <summary>The engine HTTP API (docs/roadmap/api-contract.md, rows tagged 06).</summary>
public interface IEngineClient
{
    Task<EngineHealth> GetHealthAsync(CancellationToken cancellationToken = default);

    Task<DeviceList> GetDevicesAsync(CancellationToken cancellationToken = default);

    Task<SessionSummary> StartSessionAsync(
        StartSessionRequest request, CancellationToken cancellationToken = default);

    Task<SessionSummary> PauseSessionAsync(CancellationToken cancellationToken = default);

    Task<SessionSummary> ResumeSessionAsync(CancellationToken cancellationToken = default);

    Task<SessionSummary> StopSessionAsync(CancellationToken cancellationToken = default);

    Task<SessionPage> ListSessionsAsync(
        int limit = 50, int offset = 0, CancellationToken cancellationToken = default);

    Task<SessionDetail> GetSessionAsync(string id, CancellationToken cancellationToken = default);

    /// <summary><c>GET /sessions?from=&amp;to=</c> (phase 36): the meetings of these local days (both included), grouped by day.</summary>
    Task<SessionDays> ListSessionDaysAsync(DateOnly first, DateOnly last, CancellationToken cancellationToken = default);

    /// <summary><c>DELETE /sessions/{id}</c> (phase 36): permanent in the database, to the Recycle Bin for the file backend.</summary>
    Task DeleteSessionAsync(string id, CancellationToken cancellationToken = default);

    /// <summary><c>PATCH /sessions/{id}</c> (phase 35): rename a meeting, also while recording; null clears the title.</summary>
    Task<SessionSummary> UpdateSessionTitleAsync(
        string id, string? title, CancellationToken cancellationToken = default);

    Task<Transcript> GetTranscriptAsync(string id, CancellationToken cancellationToken = default);

    Task<Minutes> GetMinutesAsync(string id, CancellationToken cancellationToken = default);

    /// <summary><c>PUT /sessions/{id}/transcript</c> (phase 21): save corrected texts of these segments.</summary>
    Task<TranscriptEditResult> UpdateTranscriptAsync(
        string id, IReadOnlyList<SegmentTextEdit> segments, CancellationToken cancellationToken = default);

    /// <summary><c>DELETE /sessions/{id}/transcript/edits</c> (phase 21): back to the original transcript.</summary>
    Task RevertTranscriptAsync(string id, CancellationToken cancellationToken = default);

    /// <summary><c>POST /sessions/{id}/minutes</c>; a null template keeps the session's own.</summary>
    Task RegenerateMinutesAsync(string id, string? templateId = null, CancellationToken cancellationToken = default);

    /// <summary><c>POST /sessions/{id}/recover</c> (phase 17): finish an interrupted session; progress via <c>status</c> events.</summary>
    Task RecoverSessionAsync(string id, CancellationToken cancellationToken = default);

    /// <summary><c>GET /templates</c>: the minutes templates in display order (phase 20).</summary>
    Task<IReadOnlyList<MinutesTemplate>> GetTemplatesAsync(CancellationToken cancellationToken = default);

    /// <summary><c>GET /sessions/{id}/speakers</c> (phase 16): names and default labels.</summary>
    Task<SessionSpeakers> GetSpeakersAsync(string id, CancellationToken cancellationToken = default);

    /// <summary><c>PUT /sessions/{id}/speakers</c> (phase 16): a null or empty name restores the default label.</summary>
    Task<SessionSpeakers> UpdateSpeakersAsync(
        string id, IReadOnlyDictionary<string, string?> names, CancellationToken cancellationToken = default);

    /// <summary><c>GET /sessions/{id}/export?format=</c>: <c>md</c>, <c>docx</c> or <c>pdf</c>.</summary>
    Task<ExportedFile> ExportSessionAsync(string id, string format, CancellationToken cancellationToken = default);

    /// <summary>
    /// <c>GET /sessions/{id}/audio/{track}</c> (phase 32): <c>mic</c>, <c>system</c> or <c>mixed</c> as a WAV,
    /// streamed into <paramref name="destination"/>.
    /// </summary>
    Task DownloadAudioAsync(string id, string track, Stream destination, CancellationToken cancellationToken = default);

    /// <summary><c>DELETE /sessions/{id}/audio</c> (phase 39): remove a meeting's audio and keep its transcript and minutes.</summary>
    Task DeleteSessionAudioAsync(string id, CancellationToken cancellationToken = default);

    /// <summary><c>GET /sessions/{id}/bundle</c> (phase 39): the meeting as a ZIP, streamed into <paramref name="destination"/>.</summary>
    Task DownloadBundleAsync(string id, Stream destination, CancellationToken cancellationToken = default);

    /// <summary><c>POST /sessions/import</c> (phase 39): read a meeting ZIP back (a new meeting, or the audio of a kept one).</summary>
    Task<ImportedSession> ImportBundleAsync(Stream bundle, CancellationToken cancellationToken = default);

    /// <summary>
    /// <c>POST /sessions/import-audio</c> (phase 60): an audio or video file recorded elsewhere becomes a
    /// meeting named after <paramref name="fileName"/>, ending at <paramref name="recordedAt"/> (or now),
    /// queued for processing like a stopped recording.
    /// </summary>
    Task<ImportedAudio> ImportAudioAsync(
        Stream audio, string fileName, DateTimeOffset? recordedAt, CancellationToken cancellationToken = default);

    /// <summary><c>GET /search</c> (phase 22): best matches first across every transcript.</summary>
    Task<SearchResults> SearchAsync(string query, int limit = 50, CancellationToken cancellationToken = default);

    /// <summary><c>POST /ask</c> (phase 24): the answer streams as <see cref="AnswerChunkEvent"/>s, then <see cref="AnswerDoneEvent"/>.</summary>
    Task<AskAccepted> AskAsync(string question, string? sessionId = null, CancellationToken cancellationToken = default);

    /// <summary><c>GET /sessions/{id}/action-items</c> (phase 23): items and configured export targets.</summary>
    Task<ActionItemList> GetActionItemsAsync(string id, CancellationToken cancellationToken = default);

    /// <summary><c>POST /sessions/{id}/action-items</c>: extract again; the result comes as <see cref="ActionItemsReadyEvent"/>.</summary>
    Task ExtractActionItemsAsync(string id, CancellationToken cancellationToken = default);

    /// <summary><c>PUT /sessions/{id}/action-items</c>: save edited items (exported ones are kept as they are).</summary>
    Task<ActionItemList> UpdateActionItemsAsync(
        string id, IReadOnlyList<ActionItemEdit> items, CancellationToken cancellationToken = default);

    /// <summary><c>POST /sessions/{id}/action-items/export</c>: one work item / issue per selected item.</summary>
    Task<ActionItemsExportResult> ExportActionItemsAsync(
        string id, string target, IReadOnlyList<string> itemIds, CancellationToken cancellationToken = default);

    Task<EngineSettings> GetSettingsAsync(CancellationToken cancellationToken = default);

    /// <summary><c>GET /vocabulary</c> (phase 19): the glossary terms.</summary>
    Task<IReadOnlyList<string>> GetVocabularyAsync(CancellationToken cancellationToken = default);

    /// <summary><c>PUT /vocabulary</c>: replaces the glossary; returns the terms as the engine cleaned them.</summary>
    Task<IReadOnlyList<string>> UpdateVocabularyAsync(
        IReadOnlyList<string> terms, CancellationToken cancellationToken = default);

    /// <summary><c>PUT /settings</c>: null clears a key; an invalid value throws with its <c>Key</c>.</summary>
    Task<SettingsUpdateResult> UpdateSettingsAsync(
        IReadOnlyDictionary<string, object?> values, CancellationToken cancellationToken = default);

    /// <summary><c>GET /settings/options</c> (phase 38): the lists the Config page offers.</summary>
    Task<SettingOptions> GetSettingOptionsAsync(CancellationToken cancellationToken = default);

    /// <summary><c>POST /settings/test/{target}</c> (phase 38): check a service with the saved settings.</summary>
    Task<ConnectionTestResult> TestConnectionAsync(string target, CancellationToken cancellationToken = default);

    /// <summary><c>DELETE /storage/cache</c> (phase 38): empty the audio cache.</summary>
    Task<CacheCleared> ClearAudioCacheAsync(CancellationToken cancellationToken = default);

    /// <summary><c>GET /migration</c> (phase 33): the import of the old meeting folders.</summary>
    Task<MigrationSummary> GetMigrationAsync(CancellationToken cancellationToken = default);

    /// <summary><c>POST /sessions/{id}/partial-minutes</c> (phase 48): minutes so far (recording) or of a range.</summary>
    Task<PartialMinutesStarted> StartPartialMinutesAsync(
        string sessionId, double? fromSeconds = null, double? toSeconds = null, string? templateId = null,
        CancellationToken cancellationToken = default);

    /// <summary><c>GET /sessions/{id}/partial-minutes</c> (phase 48).</summary>
    Task<PartialMinutesList> GetPartialMinutesAsync(string sessionId, CancellationToken cancellationToken = default);

    /// <summary><c>GET /sessions/{id}/requests</c> (phase 59): the meeting's request history.</summary>
    Task<RequestList> GetRequestsAsync(string sessionId, CancellationToken cancellationToken = default);

    /// <summary><c>GET /sessions/{id}/partial-minutes/{pid}</c> (phase 48).</summary>
    Task<PartialMinutesDetail> GetPartialMinutesItemAsync(
        string sessionId, string partialId, CancellationToken cancellationToken = default);

    /// <summary><c>DELETE /sessions/{id}/partial-minutes/{pid}</c> (phase 48).</summary>
    Task DeletePartialMinutesAsync(string sessionId, string partialId, CancellationToken cancellationToken = default);

    /// <summary><c>GET /voice-commands</c> (phase 50).</summary>
    Task<VoiceCommandsView> GetVoiceCommandsAsync(CancellationToken cancellationToken = default);

    /// <summary><c>PUT /voice-commands</c> (phase 50): replace the list; it comes back trimmed.</summary>
    Task<VoiceCommandsView> UpdateVoiceCommandsAsync(
        IReadOnlyList<VoiceCommand> commands, CancellationToken cancellationToken = default);

    /// <summary><c>GET /worker/discover</c> (phase 47): the VozAta workers on the local network.</summary>
    Task<WorkersFound> DiscoverWorkersAsync(CancellationToken cancellationToken = default);

    /// <summary><c>POST /worker/pair</c> (phase 47): trade the code shown on the worker PC for its token.</summary>
    Task<PairedWorker> PairWorkerAsync(string url, string code, CancellationToken cancellationToken = default);
}

/// <summary>The engine answered with the error envelope; <see cref="Exception.Message"/> is localized.</summary>
public sealed class EngineApiException(HttpStatusCode status, string code, string message, string? key = null)
    : Exception(message)
{
    public HttpStatusCode Status { get; } = status;

    public string Code { get; } = code;

    /// <summary>The rejected setting for <c>invalid_setting</c>.</summary>
    public string? Key { get; } = key;
}

/// <summary>The engine could not be reached (not running, starting, or crashed).</summary>
public sealed class EngineUnavailableException(string message, Exception innerException)
    : Exception(message, innerException);

public sealed class EngineClient(HttpClient http) : IEngineClient
{
    public Task<EngineHealth> GetHealthAsync(CancellationToken cancellationToken = default) =>
        SendAsync<EngineHealth>(HttpMethod.Get, "health", null, cancellationToken);

    public Task<DeviceList> GetDevicesAsync(CancellationToken cancellationToken = default) =>
        SendAsync<DeviceList>(HttpMethod.Get, "devices", null, cancellationToken);

    public Task<SessionSummary> StartSessionAsync(
        StartSessionRequest request, CancellationToken cancellationToken = default) =>
        SendAsync<SessionSummary>(HttpMethod.Post, "sessions", request, cancellationToken);

    public Task<SessionSummary> PauseSessionAsync(CancellationToken cancellationToken = default) =>
        SendAsync<SessionSummary>(HttpMethod.Post, "sessions/current/pause", null, cancellationToken);

    public Task<SessionSummary> ResumeSessionAsync(CancellationToken cancellationToken = default) =>
        SendAsync<SessionSummary>(HttpMethod.Post, "sessions/current/resume", null, cancellationToken);

    public Task<SessionSummary> StopSessionAsync(CancellationToken cancellationToken = default) =>
        SendAsync<SessionSummary>(HttpMethod.Post, "sessions/current/stop", null, cancellationToken);

    public Task<SessionPage> ListSessionsAsync(
        int limit = 50, int offset = 0, CancellationToken cancellationToken = default) =>
        SendAsync<SessionPage>(
            HttpMethod.Get, $"sessions?limit={limit}&offset={offset}", null, cancellationToken);

    public Task<SessionDetail> GetSessionAsync(
        string id, CancellationToken cancellationToken = default) =>
        SendAsync<SessionDetail>(HttpMethod.Get, $"sessions/{Escape(id)}", null, cancellationToken);

    public Task<SessionSummary> UpdateSessionTitleAsync(
        string id, string? title, CancellationToken cancellationToken = default) =>
        SendAsync<SessionSummary>(HttpMethod.Patch, $"sessions/{Escape(id)}", new { title }, cancellationToken);

    public Task<SessionDays> ListSessionDaysAsync(
        DateOnly first, DateOnly last, CancellationToken cancellationToken = default) =>
        SendAsync<SessionDays>(
            HttpMethod.Get,
            $"sessions?from={first.ToString("yyyy-MM-dd", CultureInfo.InvariantCulture)}&to={last.ToString("yyyy-MM-dd", CultureInfo.InvariantCulture)}",
            null,
            cancellationToken);

    public async Task DeleteSessionAsync(string id, CancellationToken cancellationToken = default)
    {
        using var response = await SendRawAsync(HttpMethod.Delete, $"sessions/{Escape(id)}", null, cancellationToken);
    }

    public Task<Transcript> GetTranscriptAsync(
        string id, CancellationToken cancellationToken = default) =>
        SendAsync<Transcript>(
            HttpMethod.Get, $"sessions/{Escape(id)}/transcript", null, cancellationToken);

    public Task<Minutes> GetMinutesAsync(string id, CancellationToken cancellationToken = default) =>
        SendAsync<Minutes>(HttpMethod.Get, $"sessions/{Escape(id)}/minutes", null, cancellationToken);

    public Task<TranscriptEditResult> UpdateTranscriptAsync(
        string id, IReadOnlyList<SegmentTextEdit> segments, CancellationToken cancellationToken = default) =>
        SendAsync<TranscriptEditResult>(
            HttpMethod.Put, $"sessions/{Escape(id)}/transcript", new { segments }, cancellationToken);

    public async Task RevertTranscriptAsync(string id, CancellationToken cancellationToken = default)
    {
        using var response = await SendRawAsync(
            HttpMethod.Delete, $"sessions/{Escape(id)}/transcript/edits", null, cancellationToken);
    }

    public async Task RegenerateMinutesAsync(
        string id, string? templateId = null, CancellationToken cancellationToken = default)
    {
        using var response = await SendRawAsync(
            HttpMethod.Post, $"sessions/{Escape(id)}/minutes", new { template = templateId }, cancellationToken);
    }

    public async Task RecoverSessionAsync(string id, CancellationToken cancellationToken = default)
    {
        using var response = await SendRawAsync(
            HttpMethod.Post, $"sessions/{Escape(id)}/recover", null, cancellationToken);
    }

    public Task<IReadOnlyList<MinutesTemplate>> GetTemplatesAsync(CancellationToken cancellationToken = default) =>
        SendAsync<IReadOnlyList<MinutesTemplate>>(HttpMethod.Get, "templates", null, cancellationToken);

    public Task<SessionSpeakers> GetSpeakersAsync(string id, CancellationToken cancellationToken = default) =>
        SendAsync<SessionSpeakers>(HttpMethod.Get, $"sessions/{Escape(id)}/speakers", null, cancellationToken);

    public Task<SessionSpeakers> UpdateSpeakersAsync(
        string id, IReadOnlyDictionary<string, string?> names, CancellationToken cancellationToken = default) =>
        SendAsync<SessionSpeakers>(
            HttpMethod.Put,
            $"sessions/{Escape(id)}/speakers",
            new { speakers = names.ToDictionary(pair => pair.Key, pair => new { name = pair.Value }) },
            cancellationToken);

    public Task<SearchResults> SearchAsync(
        string query, int limit = 50, CancellationToken cancellationToken = default) =>
        SendAsync<SearchResults>(
            HttpMethod.Get, $"search?q={Uri.EscapeDataString(query)}&limit={limit}", null, cancellationToken);

    public Task<AskAccepted> AskAsync(
        string question, string? sessionId = null, CancellationToken cancellationToken = default) =>
        SendAsync<AskAccepted>(HttpMethod.Post, "ask", new AskRequest(question, sessionId), cancellationToken);

    public Task<ActionItemList> GetActionItemsAsync(string id, CancellationToken cancellationToken = default) =>
        SendAsync<ActionItemList>(HttpMethod.Get, $"sessions/{Escape(id)}/action-items", null, cancellationToken);

    public async Task ExtractActionItemsAsync(string id, CancellationToken cancellationToken = default)
    {
        using var response = await SendRawAsync(
            HttpMethod.Post, $"sessions/{Escape(id)}/action-items", null, cancellationToken);
    }

    public Task<ActionItemList> UpdateActionItemsAsync(
        string id, IReadOnlyList<ActionItemEdit> items, CancellationToken cancellationToken = default) =>
        SendAsync<ActionItemList>(HttpMethod.Put, $"sessions/{Escape(id)}/action-items", new { items }, cancellationToken);

    public Task<ActionItemsExportResult> ExportActionItemsAsync(
        string id, string target, IReadOnlyList<string> itemIds, CancellationToken cancellationToken = default) =>
        SendAsync<ActionItemsExportResult>(
            HttpMethod.Post,
            $"sessions/{Escape(id)}/action-items/export",
            new { target, item_ids = itemIds },
            cancellationToken);

    public Task<EngineSettings> GetSettingsAsync(CancellationToken cancellationToken = default) =>
        SendAsync<EngineSettings>(HttpMethod.Get, "settings", null, cancellationToken);

    public async Task<IReadOnlyList<string>> GetVocabularyAsync(CancellationToken cancellationToken = default) =>
        (await SendAsync<VocabularyTerms>(HttpMethod.Get, "vocabulary", null, cancellationToken)).Terms;

    public async Task<IReadOnlyList<string>> UpdateVocabularyAsync(
        IReadOnlyList<string> terms, CancellationToken cancellationToken = default) =>
        (await SendAsync<VocabularyTerms>(
            HttpMethod.Put, "vocabulary", new VocabularyTerms(terms), cancellationToken)).Terms;

    public async Task<ExportedFile> ExportSessionAsync(
        string id, string format, CancellationToken cancellationToken = default)
    {
        using var response = await SendRawAsync(
            HttpMethod.Get, $"sessions/{Escape(id)}/export?format={Uri.EscapeDataString(format)}", null, cancellationToken);
        var content = await response.Content.ReadAsByteArrayAsync(cancellationToken);
        var name = response.Content.Headers.ContentDisposition?.FileName?.Trim('"');
        return new ExportedFile(string.IsNullOrEmpty(name) ? $"{id}-minutes.{format}" : name, content);
    }

    public async Task DownloadAudioAsync(
        string id, string track, Stream destination, CancellationToken cancellationToken = default)
    {
        using var response = await SendRawAsync(
            HttpMethod.Get, $"sessions/{Escape(id)}/audio/{Escape(track)}", null, cancellationToken,
            HttpCompletionOption.ResponseHeadersRead);
        await response.Content.CopyToAsync(destination, cancellationToken);
    }

    public async Task DeleteSessionAudioAsync(string id, CancellationToken cancellationToken = default)
    {
        using var response = await SendRawAsync(HttpMethod.Delete, $"sessions/{Escape(id)}/audio", null, cancellationToken);
    }

    public async Task DownloadBundleAsync(string id, Stream destination, CancellationToken cancellationToken = default)
    {
        using var response = await SendRawAsync(
            HttpMethod.Get, $"sessions/{Escape(id)}/bundle", null, cancellationToken,
            HttpCompletionOption.ResponseHeadersRead);
        await response.Content.CopyToAsync(destination, cancellationToken);
    }

    public async Task<ImportedSession> ImportBundleAsync(Stream bundle, CancellationToken cancellationToken = default)
    {
        var content = new StreamContent(bundle);
        content.Headers.ContentType = new MediaTypeHeaderValue("application/zip");
        using var response = await SendRawAsync(HttpMethod.Post, "sessions/import", content, cancellationToken);
        var value = await response.Content.ReadFromJsonAsync<ImportedSession>(EngineJson.Options, cancellationToken);
        return value ?? throw new JsonException("Empty response from sessions/import");
    }

    public async Task<ImportedAudio> ImportAudioAsync(
        Stream audio, string fileName, DateTimeOffset? recordedAt, CancellationToken cancellationToken = default)
    {
        var content = new StreamContent(audio);
        content.Headers.ContentType = new MediaTypeHeaderValue("application/octet-stream");
        var path = $"sessions/import-audio?name={Escape(fileName)}";
        if (recordedAt is { } time)
        {
            path += $"&recorded_at={Escape(time.ToString("yyyy-MM-ddTHH:mm:sszzz", CultureInfo.InvariantCulture))}";
        }

        using var response = await SendRawAsync(HttpMethod.Post, path, content, cancellationToken);
        var value = await response.Content.ReadFromJsonAsync<ImportedAudio>(EngineJson.Options, cancellationToken);
        return value ?? throw new JsonException("Empty response from sessions/import-audio");
    }

    public Task<SettingsUpdateResult> UpdateSettingsAsync(
        IReadOnlyDictionary<string, object?> values, CancellationToken cancellationToken = default) =>
        SendAsync<SettingsUpdateResult>(HttpMethod.Put, "settings", new { values }, cancellationToken);

    public Task<SettingOptions> GetSettingOptionsAsync(CancellationToken cancellationToken = default) =>
        SendAsync<SettingOptions>(HttpMethod.Get, "settings/options", null, cancellationToken);

    public Task<ConnectionTestResult> TestConnectionAsync(string target, CancellationToken cancellationToken = default) =>
        SendAsync<ConnectionTestResult>(HttpMethod.Post, $"settings/test/{Escape(target)}", null, cancellationToken);

    public Task<MigrationSummary> GetMigrationAsync(CancellationToken cancellationToken = default) =>
        SendAsync<MigrationSummary>(HttpMethod.Get, "migration", null, cancellationToken);

    public Task<PartialMinutesStarted> StartPartialMinutesAsync(
        string sessionId, double? fromSeconds = null, double? toSeconds = null, string? templateId = null,
        CancellationToken cancellationToken = default) =>
        SendAsync<PartialMinutesStarted>(
            HttpMethod.Post, $"sessions/{Escape(sessionId)}/partial-minutes", new { start = fromSeconds, end = toSeconds, template = templateId }, cancellationToken);

    public Task<PartialMinutesList> GetPartialMinutesAsync(string sessionId, CancellationToken cancellationToken = default) =>
        SendAsync<PartialMinutesList>(HttpMethod.Get, $"sessions/{Escape(sessionId)}/partial-minutes", null, cancellationToken);

    public Task<RequestList> GetRequestsAsync(string sessionId, CancellationToken cancellationToken = default) =>
        SendAsync<RequestList>(HttpMethod.Get, $"sessions/{Escape(sessionId)}/requests", null, cancellationToken);

    public Task<PartialMinutesDetail> GetPartialMinutesItemAsync(
        string sessionId, string partialId, CancellationToken cancellationToken = default) =>
        SendAsync<PartialMinutesDetail>(
            HttpMethod.Get, $"sessions/{Escape(sessionId)}/partial-minutes/{Escape(partialId)}", null, cancellationToken);

    public async Task DeletePartialMinutesAsync(string sessionId, string partialId, CancellationToken cancellationToken = default)
    {
        using var response = await SendRawAsync(
            HttpMethod.Delete, $"sessions/{Escape(sessionId)}/partial-minutes/{Escape(partialId)}", null, cancellationToken);
    }

    public Task<VoiceCommandsView> GetVoiceCommandsAsync(CancellationToken cancellationToken = default) =>
        SendAsync<VoiceCommandsView>(HttpMethod.Get, "voice-commands", null, cancellationToken);

    public Task<VoiceCommandsView> UpdateVoiceCommandsAsync(
        IReadOnlyList<VoiceCommand> commands, CancellationToken cancellationToken = default) =>
        SendAsync<VoiceCommandsView>(HttpMethod.Put, "voice-commands", new { commands }, cancellationToken);

    public Task<WorkersFound> DiscoverWorkersAsync(CancellationToken cancellationToken = default) =>
        SendAsync<WorkersFound>(HttpMethod.Get, "worker/discover", null, cancellationToken);

    public Task<PairedWorker> PairWorkerAsync(string url, string code, CancellationToken cancellationToken = default) =>
        SendAsync<PairedWorker>(HttpMethod.Post, "worker/pair", new { url, code }, cancellationToken);

    public Task<CacheCleared> ClearAudioCacheAsync(CancellationToken cancellationToken = default) =>
        SendAsync<CacheCleared>(HttpMethod.Delete, "storage/cache", null, cancellationToken);

    private async Task<T> SendAsync<T>(
        HttpMethod method, string path, object? body, CancellationToken cancellationToken)
    {
        using var response = await SendRawAsync(method, path, body, cancellationToken);
        var value = await response.Content.ReadFromJsonAsync<T>(EngineJson.Options, cancellationToken);
        return value ?? throw new JsonException($"Empty response from {path}");
    }

    private async Task<HttpResponseMessage> SendRawAsync(
        HttpMethod method,
        string path,
        object? body,
        CancellationToken cancellationToken,
        HttpCompletionOption completion = HttpCompletionOption.ResponseContentRead)
    {
        using var request = new HttpRequestMessage(method, path);
        if (body is not null)
        {
            request.Content = body as HttpContent ?? JsonContent.Create(body, options: EngineJson.Options);
        }

        HttpResponseMessage response;
        try
        {
            response = await http.SendAsync(request, completion, cancellationToken);
        }
        catch (HttpRequestException error)
        {
            throw new EngineUnavailableException(error.Message, error);
        }

        if (response.IsSuccessStatusCode)
        {
            return response;
        }

        using (response)
        {
            throw await ToExceptionAsync(response, cancellationToken);
        }
    }

    private static async Task<Exception> ToExceptionAsync(
        HttpResponseMessage response, CancellationToken cancellationToken)
    {
        var text = await response.Content.ReadAsStringAsync(cancellationToken);
        try
        {
            var envelope = JsonSerializer.Deserialize<ErrorEnvelope>(text, EngineJson.Options);
            if (envelope?.Error is { } error)
            {
                return new EngineApiException(response.StatusCode, error.Code, error.Message, error.Key);
            }
        }
        catch (JsonException)
        {
            // Not the envelope (e.g. a proxy page): fall through to a generic error.
        }

        return new EngineApiException(
            response.StatusCode, "http_error", $"HTTP {(int)response.StatusCode}");
    }

    private static string Escape(string id) => Uri.EscapeDataString(id);

    private sealed record ErrorEnvelope(ErrorBody? Error);

    private sealed record ErrorBody(string Code, string Message, string? Key);
}
