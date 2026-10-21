using System.Net.WebSockets;
using VozAta.Client;

namespace VozAta.Desktop.Tests;

public sealed class EngineEventsTests
{
    private static readonly Uri Ws = new("ws://127.0.0.1:8765/ws");

    [Fact]
    public void Parses_processing_event_with_and_without_position()
    {
        Assert.Equal(
            new ProcessingEvent("s1", new ProcessingInfo("queued", 0, null, 2)),
            EngineEventParser.Parse("""{"type":"processing","session_id":"s1","data":{"state":"queued","percent":0,"step":null,"position":2}}"""));
        Assert.Equal(
            new ProcessingEvent("s1", new ProcessingInfo("running", 40, "transcribe", null)),
            EngineEventParser.Parse("""{"type":"processing","session_id":"s1","data":{"state":"running","percent":40,"step":"transcribe"}}"""));
    }

    [Fact]
    public void Parser_reads_every_known_event_type()
    {
        Assert.Equal(
            new StatusEvent("s1", "recording", 2.5),
            EngineEventParser.Parse("""{"type":"status","session_id":"s1","data":{"status":"recording","duration_seconds":2.5}}"""));
        Assert.Equal(
            new StatusEvent(null, "idle", null),
            EngineEventParser.Parse("""{"type":"status","session_id":null,"data":{"status":"idle"}}"""));
        Assert.Equal(
            new LevelEvent("s1", "mic", -20.5),
            EngineEventParser.Parse("""{"type":"level","session_id":"s1","data":{"channel":"mic","rms_db":-20.5}}"""));
        Assert.Equal(
            new LanguageDetectedEvent("s1", "pt"),
            EngineEventParser.Parse("""{"type":"language_detected","session_id":"s1","data":{"language":"pt"}}"""));
        Assert.Equal(
            new MinutesReadyEvent("s1"),
            EngineEventParser.Parse("""{"type":"minutes_ready","session_id":"s1","data":{"session_id":"s1"}}"""));
        Assert.Equal(
            new ErrorEvent("s1", "minutes_failed", "Ollama offline"),
            EngineEventParser.Parse("""{"type":"error","session_id":"s1","data":{"code":"minutes_failed","message":"Ollama offline"}}"""));
        Assert.Equal(
            new PartialEvent("s1", "system", "system", "Outros", 12.5, "Vamos começ"),
            EngineEventParser.Parse("""{"type":"partial","session_id":"s1","data":{"channel":"system","speaker_id":"system","label":"Outros","start":12.5,"text":"Vamos começ"}}"""));
        Assert.Equal(
            new ModelLoadingEvent("s1", true),
            EngineEventParser.Parse("""{"type":"model_loading","session_id":"s1","data":{"loading":true}}"""));
        Assert.Equal(
            new TranslationEvent("s1", "mic-000001", "pt", "Bom dia"),
            EngineEventParser.Parse("""{"type":"translation","session_id":"s1","data":{"segment_id":"mic-000001","language":"pt","text":"Bom dia"}}"""));
        Assert.Equal(
            new SpeakersRelabeledEvent("s1"),
            EngineEventParser.Parse("""{"type":"speakers_relabeled","session_id":"s1","data":{"session_id":"s1"}}"""));
        Assert.Equal(
            new UnknownEvent("s1", "future_event"),
            EngineEventParser.Parse("""{"type":"future_event","session_id":"s1","data":{}}"""));
    }

    [Fact]
    public void Parses_download_progress_with_and_without_total()
    {
        Assert.Equal(
            new DownloadProgressEvent(null, "speech", "large-v3-turbo", 1024, 4096, "running", null),
            EngineEventParser.Parse(
                """{"type":"download_progress","session_id":null,"data":{"kind":"speech","model":"large-v3-turbo","downloaded_bytes":1024,"total_bytes":4096,"state":"running"}}"""));
        Assert.Equal(
            new DownloadProgressEvent(null, "translation", "ROMANCE-en", 10, null, "failed", "no network"),
            EngineEventParser.Parse(
                """{"type":"download_progress","session_id":null,"data":{"kind":"translation","model":"ROMANCE-en","downloaded_bytes":10,"total_bytes":null,"state":"failed","reason":"no network"}}"""));
        Assert.Equal(
            new DownloadProgressEvent(null, "speakers", "community-1", 5, null, "running", null),
            EngineEventParser.Parse(
                """{"type":"download_progress","session_id":null,"data":{"kind":"speakers","model":"community-1","downloaded_bytes":5,"state":"running"}}"""));
    }

    [Fact]
    public void Parser_reads_the_recovery_offer()
    {
        var parsed = EngineEventParser.Parse(
            """{"type":"recovery_available","session_id":null,"data":{"session_ids":["20261015_202358","20261014_090000"]}}""");

        var offer = Assert.IsType<RecoveryAvailableEvent>(parsed);
        Assert.Null(offer.SessionId);
        Assert.Equal(["20261015_202358", "20261014_090000"], offer.SessionIds);
        Assert.Null(EngineEventParser.Parse("""{"type":"recovery_available","session_id":null,"data":{"session_ids":null}}"""));
    }

    [Fact]
    public void Parser_reads_segments_with_labels()
    {
        var parsed = EngineEventParser.Parse("""
            {"type":"segment","session_id":"s1","data":{"segment_id":"mic-000001","channel":"mic",
             "speaker_id":"mic","label":"Me","start":1.0,"end":2.0,"text":"Oi.","edited":false,"words":[]}}
            """);

        var segment = Assert.IsType<SegmentEvent>(parsed).Segment;
        Assert.Equal(("mic-000001", "Me", "Oi."), (segment.SegmentId, segment.Label, segment.Text));
    }

    [Theory]
    [InlineData("not json")]
    [InlineData("""{"type":"status"}""")]
    [InlineData("""{"type":"segment","session_id":null,"data":null}""")]
    [InlineData("""{"type":"level","session_id":"s","data":{"channel":"mic","rms_db":"loud"}}""")]
    public void Parser_ignores_invalid_envelopes(string json)
    {
        Assert.Null(EngineEventParser.Parse(json));
    }

    [Fact]
    public async Task Stream_reports_connection_then_events_and_skips_invalid_messages()
    {
        var connector = new FakeConnector(
            new FakeSocket("""{"type":"status","session_id":null,"data":{"status":"idle"}}""", "garbage"));
        using var stop = new CancellationTokenSource();

        var events = await TakeAsync(new EngineEvents(Ws, connector, NoDelay), 2, stop);

        Assert.Equal(
            [new ConnectionChangedEvent(true), new StatusEvent(null, "idle", null)],
            events);
        Assert.Equal(Ws, connector.Uris.Single());
    }

    [Fact]
    public async Task Stream_reconnects_after_a_drop_with_growing_then_reset_backoff()
    {
        var delays = new List<TimeSpan>();
        var connector = new FakeConnector(
            new FakeSocket(),  // connects, then closes at once
            null,              // connection refused
            null,              // refused again
            new FakeSocket("""{"type":"minutes_ready","session_id":"s","data":{}}"""));
        using var stop = new CancellationTokenSource();
        var stream = new EngineEvents(Ws, connector, (wait, _) =>
        {
            delays.Add(wait);
            return Task.CompletedTask;
        });

        var events = await TakeAsync(stream, 4, stop);

        Assert.Equal(
            [new ConnectionChangedEvent(true), new ConnectionChangedEvent(false),
             new ConnectionChangedEvent(true), new MinutesReadyEvent("s")],
            events);
        Assert.Equal(
            [TimeSpan.FromSeconds(0.5), TimeSpan.FromSeconds(1), TimeSpan.FromSeconds(2)],
            delays);
    }

    [Fact]
    public async Task Backoff_never_exceeds_ten_seconds()
    {
        var delays = new List<TimeSpan>();
        using var stop = new CancellationTokenSource();
        var stream = new EngineEvents(Ws, new FakeConnector(), (wait, _) =>
        {
            delays.Add(wait);
            if (delays.Count == 8)
            {
                stop.Cancel();
            }

            return Task.CompletedTask;
        });

        await foreach (var _ in stream.ReadAllAsync(stop.Token))
        {
        }

        Assert.Equal(TimeSpan.FromSeconds(10), delays[^1]);
        Assert.Equal(TimeSpan.FromSeconds(8), delays[4]);
    }

    [Fact]
    public async Task Receive_errors_count_as_a_drop()
    {
        var connector = new FakeConnector(new FakeSocket(new WebSocketException("reset")));
        using var stop = new CancellationTokenSource();

        var events = await TakeAsync(new EngineEvents(Ws, connector, NoDelay), 2, stop);

        Assert.Equal([new ConnectionChangedEvent(true), new ConnectionChangedEvent(false)], events);
    }

    [Fact]
    public async Task Cancelling_ends_the_stream_without_a_drop_event()
    {
        using var stop = new CancellationTokenSource();
        var socket = new FakeSocket(hangAtEnd: true);
        var stream = new EngineEvents(Ws, new FakeConnector(socket), NoDelay);
        var events = new List<EngineEvent>();

        await foreach (var engineEvent in stream.ReadAllAsync(stop.Token))
        {
            events.Add(engineEvent);
            stop.Cancel();
        }

        Assert.Equal([new ConnectionChangedEvent(true)], events);
        Assert.True(socket.Disposed);
    }

    [Fact]
    public async Task Cancelling_during_the_retry_delay_ends_the_stream()
    {
        using var stop = new CancellationTokenSource();
        var stream = new EngineEvents(Ws, new FakeConnector(), async (wait, token) =>
        {
            await stop.CancelAsync();
            token.ThrowIfCancellationRequested();
        });

        await foreach (var _ in stream.ReadAllAsync(stop.Token))
        {
            Assert.Fail("no event expected");
        }
    }

    private static Task NoDelay(TimeSpan wait, CancellationToken token) => Task.CompletedTask;

    private static async Task<List<EngineEvent>> TakeAsync(
        EngineEvents stream, int count, CancellationTokenSource stop)
    {
        var events = new List<EngineEvent>();
        await foreach (var engineEvent in stream.ReadAllAsync(stop.Token))
        {
            events.Add(engineEvent);
            if (events.Count == count)
            {
                await stop.CancelAsync();
            }
        }

        return events;
    }

    /// <summary>Hands out the given sockets in order; null (or running out) refuses the connection.</summary>
    private sealed class FakeConnector(params FakeSocket?[] sockets) : IEventSocketConnector
    {
        private readonly Queue<FakeSocket?> _sockets = new(sockets);

        public List<Uri> Uris { get; } = [];

        public Task<IEventSocket> ConnectAsync(Uri uri, CancellationToken cancellationToken)
        {
            Uris.Add(uri);
            cancellationToken.ThrowIfCancellationRequested();
            if (_sockets.Count == 0 || _sockets.Dequeue() is not { } socket)
            {
                throw new WebSocketException("refused");
            }

            return Task.FromResult<IEventSocket>(socket);
        }
    }

    private sealed class FakeSocket : IEventSocket
    {
        private readonly Queue<object> _messages;
        private readonly bool _hangAtEnd;

        public FakeSocket(params object[] messages) : this(false, messages)
        {
        }

        public FakeSocket(bool hangAtEnd, params object[] messages)
        {
            _messages = new Queue<object>(messages);
            _hangAtEnd = hangAtEnd;
        }

        public bool Disposed { get; private set; }

        public async Task<string?> ReceiveAsync(CancellationToken cancellationToken)
        {
            if (_messages.Count == 0)
            {
                if (_hangAtEnd)
                {
                    await Task.Delay(Timeout.Infinite, cancellationToken);
                }

                return null;
            }

            return _messages.Dequeue() switch
            {
                Exception error => throw error,
                var text => (string)text,
            };
        }

        public ValueTask DisposeAsync()
        {
            Disposed = true;
            return ValueTask.CompletedTask;
        }
    }
}
