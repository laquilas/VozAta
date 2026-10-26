using VozAta.Client;
using VozAta.Desktop.Tests.Fakes;

namespace VozAta.Desktop.Tests;

/// <summary>The request history route and events (phase 59) on the wire.</summary>
public sealed class RequestsClientTests
{
    private const string EntryJson = """
        {"id": "r1", "created_at": "2026-10-23T10:05:00-03:00", "at": 312.5, "kind": "minutes_so_far",
         "source": "voice", "text": "gere a ata", "status": "done", "result_id": "p1", "message": null,
         "finished_at": "2026-10-23T10:05:40-03:00"}
        """;

    private static readonly RequestEntry Entry = new(
        "r1", "2026-10-23T10:05:00-03:00", 312.5, "minutes_so_far", "voice", "gere a ata", "done", "p1", null,
        "2026-10-23T10:05:40-03:00");

    [Fact]
    public async Task The_history_of_a_meeting_is_read()
    {
        var handler = FakeHttpHandler.Json($$"""{"items": [{{EntryJson}}]}""");

        var list = await new EngineClient(handler.Client()).GetRequestsAsync("s1");

        Assert.Equal(Entry, Assert.Single(list.Items));
        Assert.Equal((HttpMethod.Get, "/sessions/s1/requests"), (handler.Requests[0].Method, handler.Requests[0].Path));
    }

    [Fact]
    public void The_update_event_is_parsed()
    {
        var parsed = EngineEventParser.Parse($$$"""
            {"type": "request_updated", "session_id": "s1", "data": {"request": {{{EntryJson}}}}}
            """);

        Assert.Equal(new RequestUpdatedEvent("s1", Entry), parsed);
        Assert.True(Entry.IsFinished);
        Assert.False((Entry with { Status = "running" }).IsFinished);
    }

    [Fact]
    public void A_voice_command_carries_its_request_and_second()
    {
        var parsed = EngineEventParser.Parse("""
            {"type": "voice_command", "session_id": "s1",
             "data": {"action": "minutes", "phrase": "gere a ata", "question": null, "answer_id": null,
                      "request_id": "r1", "at": 312.5}}
            """);

        Assert.Equal(new VoiceCommandEvent("s1", "minutes", "gere a ata", null, null, "r1", 312.5), parsed);
    }

    [Fact]
    public void An_older_voice_command_has_no_request()
    {
        var parsed = EngineEventParser.Parse("""
            {"type": "voice_command", "session_id": "s1",
             "data": {"action": "minutes", "phrase": "gere a ata", "question": null, "answer_id": null}}
            """);

        Assert.Equal(new VoiceCommandEvent("s1", "minutes", "gere a ata", null, null), parsed);
    }
}
