using VozAta.Client;
using VozAta.Desktop.Tests.Fakes;

namespace VozAta.Desktop.Tests;

/// <summary>The partial minutes routes and event (phase 48) on the wire.</summary>
public sealed class PartialMinutesClientTests
{
    [Fact]
    public async Task Starting_posts_the_range_and_template()
    {
        var handler = FakeHttpHandler.Json("""{"partial_id": "p1"}""");

        var started = await new EngineClient(handler.Client()).StartPartialMinutesAsync("s1", 152, 774, "daily");

        Assert.Equal("p1", started.PartialId);
        Assert.Equal((HttpMethod.Post, "/sessions/s1/partial-minutes"), (handler.Requests[0].Method, handler.Requests[0].Path));
        Assert.Equal("""{"start":152,"end":774,"template":"daily"}""", handler.Requests[0].Body);
    }

    [Fact]
    public async Task Minutes_so_far_send_no_range()
    {
        var handler = FakeHttpHandler.Json("""{"partial_id": "p1"}""");

        await new EngineClient(handler.Client()).StartPartialMinutesAsync("s1");

        Assert.Equal("""{"start":null,"end":null,"template":null}""", handler.Requests[0].Body);
    }

    [Fact]
    public async Task The_list_one_item_and_delete()
    {
        const string listJson = """
            {"items": [{"id": "p1", "created_at": "2026-10-16T09:12:00-03:00", "start": 0, "end": 754.5,
                        "origin": "button", "template": "general"}]}
            """;
        const string itemJson = """
            {"id": "p1", "created_at": "t", "start": 0, "end": 1, "origin": "range", "template": null, "markdown": "# A\n"}
            """;
        var handler = new FakeHttpHandler(request => request.Method == HttpMethod.Delete
            ? new HttpResponseMessage(System.Net.HttpStatusCode.NoContent)
            : new HttpResponseMessage(System.Net.HttpStatusCode.OK)
            {
                Content = new StringContent(
                    request.RequestUri!.AbsolutePath.EndsWith("/p1", StringComparison.Ordinal) ? itemJson : listJson,
                    System.Text.Encoding.UTF8,
                    "application/json"),
            });
        var client = new EngineClient(handler.Client());

        var list = await client.GetPartialMinutesAsync("s1");
        var item = await client.GetPartialMinutesItemAsync("s1", "p1");
        await client.DeletePartialMinutesAsync("s1", "p1");

        Assert.Equal(new PartialMinutesSummary("p1", "2026-10-16T09:12:00-03:00", 0, 754.5, "button", "general"), Assert.Single(list.Items));
        Assert.Equal("# A\n", item.Markdown);
        Assert.Equal(
            ["GET /sessions/s1/partial-minutes", "GET /sessions/s1/partial-minutes/p1", "DELETE /sessions/s1/partial-minutes/p1"],
            handler.Requests.Select(request => $"{request.Method} {request.Path}"));
    }

    [Fact]
    public void The_ready_event_is_parsed()
    {
        var parsed = EngineEventParser.Parse("""
            {"type": "partial_minutes_ready", "session_id": "s1",
             "data": {"partial_id": "p1", "start": 0, "end": 754.5, "origin": "button"}}
            """);

        Assert.Equal(new PartialMinutesReadyEvent("s1", "p1", 0, 754.5, "button"), parsed);
    }
}
