using System.Diagnostics.CodeAnalysis;
using System.Net.WebSockets;
using System.Runtime.CompilerServices;
using System.Text;
using System.Text.Json;

namespace VozAta.Client;

// WebSocket `/ws` events (api-contract "WebSocket /ws"): envelope {type, session_id, data}.

public abstract record EngineEvent(string? SessionId);

public sealed record StatusEvent(string? SessionId, string Status, double? DurationSeconds)
    : EngineEvent(SessionId);

public sealed record LevelEvent(string? SessionId, string Channel, double RmsDb) : EngineEvent(SessionId);

public sealed record SegmentEvent(string? SessionId, Segment Segment) : EngineEvent(SessionId);

public sealed record LanguageDetectedEvent(string? SessionId, string Language) : EngineEvent(SessionId);

public sealed record MinutesReadyEvent(string? SessionId) : EngineEvent(SessionId);

public sealed record ErrorEvent(string? SessionId, string Code, string Message) : EngineEvent(SessionId);

/// <summary>The speech model started (true) or finished (false) loading while the session already records.</summary>
public sealed record ModelLoadingEvent(string? SessionId, bool Loading) : EngineEvent(SessionId);

/// <summary>An event type this client does not know yet (added by a later phase).</summary>
public sealed record UnknownEvent(string? SessionId, string Type) : EngineEvent(SessionId);

/// <summary>Not sent by the engine: the stream reports (re)connections and drops.</summary>
public sealed record ConnectionChangedEvent(bool Connected) : EngineEvent((string?)null);

public static class EngineEventParser
{
    /// <summary>The typed event of one envelope; null when the text is not a valid envelope.</summary>
    public static EngineEvent? Parse(string json)
    {
        try
        {
            using var document = JsonDocument.Parse(json);
            var root = document.RootElement;
            var type = root.GetProperty("type").GetString() ?? "";
            var sessionId = root.TryGetProperty("session_id", out var id) ? id.GetString() : null;
            var data = root.GetProperty("data");
            return type switch
            {
                "status" => new StatusEvent(
                    sessionId,
                    data.GetProperty("status").GetString() ?? "",
                    data.TryGetProperty("duration_seconds", out var duration) ? duration.GetDouble() : null),
                "level" => new LevelEvent(
                    sessionId, data.GetProperty("channel").GetString() ?? "", data.GetProperty("rms_db").GetDouble()),
                "segment" => new SegmentEvent(
                    sessionId, data.Deserialize<Segment>(EngineJson.Options) ?? throw new JsonException()),
                "language_detected" => new LanguageDetectedEvent(
                    sessionId, data.GetProperty("language").GetString() ?? ""),
                "minutes_ready" => new MinutesReadyEvent(sessionId),
                "model_loading" => new ModelLoadingEvent(sessionId, data.GetProperty("loading").GetBoolean()),
                "error" => new ErrorEvent(
                    sessionId, data.GetProperty("code").GetString() ?? "", data.GetProperty("message").GetString() ?? ""),
                _ => new UnknownEvent(sessionId, type),
            };
        }
        catch (Exception error) when (error is JsonException or KeyNotFoundException or InvalidOperationException)
        {
            return null;
        }
    }
}

/// <summary>One open event connection; <see cref="ReceiveAsync"/> returns null once closed.</summary>
public interface IEventSocket : IAsyncDisposable
{
    Task<string?> ReceiveAsync(CancellationToken cancellationToken);
}

public interface IEventSocketConnector
{
    Task<IEventSocket> ConnectAsync(Uri uri, CancellationToken cancellationToken);
}

/// <summary>The engine event stream.</summary>
public interface IEngineEvents
{
    /// <summary>Events until cancelled; reconnects by itself and reports it with <see cref="ConnectionChangedEvent"/>.</summary>
    IAsyncEnumerable<EngineEvent> ReadAllAsync(CancellationToken cancellationToken = default);
}

public sealed class EngineEvents(
    Uri uri,
    IEventSocketConnector connector,
    Func<TimeSpan, CancellationToken, Task>? delay = null) : IEngineEvents
{
    public static readonly TimeSpan FirstRetry = TimeSpan.FromSeconds(0.5);
    public static readonly TimeSpan MaxRetry = TimeSpan.FromSeconds(10);

    private readonly Func<TimeSpan, CancellationToken, Task> _delay = delay ?? Task.Delay;

    public async IAsyncEnumerable<EngineEvent> ReadAllAsync(
        [EnumeratorCancellation] CancellationToken cancellationToken = default)
    {
        var retry = FirstRetry;
        while (!cancellationToken.IsCancellationRequested)
        {
            var socket = await TryConnectAsync(cancellationToken);
            if (socket is not null)
            {
                retry = FirstRetry;
                await using (socket)
                {
                    yield return new ConnectionChangedEvent(true);
                    while (await TryReceiveAsync(socket, cancellationToken) is { } text)
                    {
                        if (EngineEventParser.Parse(text) is { } engineEvent)
                        {
                            yield return engineEvent;
                        }
                    }
                }

                if (cancellationToken.IsCancellationRequested)
                {
                    yield break;
                }

                yield return new ConnectionChangedEvent(false);
            }

            if (!await TryDelayAsync(retry, cancellationToken))
            {
                yield break;
            }

            retry = TimeSpan.FromTicks(Math.Min(retry.Ticks * 2, MaxRetry.Ticks));
        }
    }

    private async Task<IEventSocket?> TryConnectAsync(CancellationToken cancellationToken)
    {
        try
        {
            return await connector.ConnectAsync(uri, cancellationToken);
        }
        catch (Exception error) when (error is WebSocketException or HttpRequestException or OperationCanceledException)
        {
            return null;
        }
    }

    private static async Task<string?> TryReceiveAsync(IEventSocket socket, CancellationToken cancellationToken)
    {
        try
        {
            return await socket.ReceiveAsync(cancellationToken);
        }
        catch (Exception error) when (error is WebSocketException or OperationCanceledException)
        {
            return null;
        }
    }

    private async Task<bool> TryDelayAsync(TimeSpan wait, CancellationToken cancellationToken)
    {
        try
        {
            await _delay(wait, cancellationToken);
            return !cancellationToken.IsCancellationRequested;
        }
        catch (OperationCanceledException)
        {
            return false;
        }
    }
}

/// <summary>The real socket: <see cref="ClientWebSocket"/> with whole text messages.</summary>
[ExcludeFromCodeCoverage(Justification = "Thin wrapper over the network; covered by the manual check.")]
public sealed class ClientWebSocketConnector : IEventSocketConnector
{
    public async Task<IEventSocket> ConnectAsync(Uri uri, CancellationToken cancellationToken)
    {
        var socket = new ClientWebSocket();
        try
        {
            await socket.ConnectAsync(uri, cancellationToken);
            return new Socket(socket);
        }
        catch
        {
            socket.Dispose();
            throw;
        }
    }

    private sealed class Socket(ClientWebSocket socket) : IEventSocket
    {
        private readonly byte[] _buffer = new byte[16 * 1024];

        public async Task<string?> ReceiveAsync(CancellationToken cancellationToken)
        {
            using var message = new MemoryStream();
            while (true)
            {
                var result = await socket.ReceiveAsync(_buffer, cancellationToken);
                if (result.MessageType == WebSocketMessageType.Close)
                {
                    return null;
                }

                message.Write(_buffer, 0, result.Count);
                if (result.EndOfMessage)
                {
                    return Encoding.UTF8.GetString(message.GetBuffer(), 0, (int)message.Length);
                }
            }
        }

        public async ValueTask DisposeAsync()
        {
            if (socket.State == WebSocketState.Open)
            {
                using var timeout = new CancellationTokenSource(TimeSpan.FromSeconds(2));
                try
                {
                    await socket.CloseAsync(WebSocketCloseStatus.NormalClosure, null, timeout.Token);
                }
                catch (Exception error) when (error is WebSocketException or OperationCanceledException)
                {
                    // The engine is gone; nothing left to close.
                }
            }

            socket.Dispose();
        }
    }
}
