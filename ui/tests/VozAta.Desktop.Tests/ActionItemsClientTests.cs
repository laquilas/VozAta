using System.Net;
using VozAta.Client;
using VozAta.Desktop.Tests.Fakes;

namespace VozAta.Desktop.Tests;

public sealed class ActionItemsClientTests
{
    private const string ListJson = """
        {"items": [{"id": "a1", "description": "Send", "owner": "Ana", "due": null,
                    "source_segment_ids": ["mic-000002"], "exported_url": "https://x.test/1"}],
         "targets": ["github"]}
        """;

    [Fact]
    public async Task Get_reads_items_and_targets()
    {
        var handler = FakeHttpHandler.Json(ListJson);

        var list = await new EngineClient(handler.Client()).GetActionItemsAsync("20261015_202358");

        var item = Assert.Single(list.Items);
        Assert.Equal(("a1", "Send", "Ana", null), (item.Id, item.Description, item.Owner, item.Due));
        Assert.Equal(["mic-000002"], item.SourceSegmentIds);
        Assert.Equal("https://x.test/1", item.ExportedUrl);
        Assert.Equal(["github"], list.Targets);
        var request = handler.Requests.Single();
        Assert.Equal((HttpMethod.Get, "/sessions/20261015_202358/action-items"), (request.Method, request.Path));
    }

    [Fact]
    public async Task Extract_posts_without_a_body()
    {
        var handler = FakeHttpHandler.Json("null", HttpStatusCode.Accepted);

        await new EngineClient(handler.Client()).ExtractActionItemsAsync("20261015_202358");

        var request = handler.Requests.Single();
        Assert.Equal((HttpMethod.Post, "/sessions/20261015_202358/action-items"), (request.Method, request.Path));
    }

    [Fact]
    public async Task Update_puts_the_edited_items()
    {
        var handler = FakeHttpHandler.Json(ListJson);

        await new EngineClient(handler.Client()).UpdateActionItemsAsync(
            "20261015_202358", [new ActionItemEdit("a1", "Send", null, "Friday")]);

        var request = handler.Requests.Single();
        Assert.Equal((HttpMethod.Put, "/sessions/20261015_202358/action-items"), (request.Method, request.Path));
        Assert.Equal("""{"items":[{"id":"a1","description":"Send","owner":null,"due":"Friday"}]}""", request.Body);
    }

    [Fact]
    public async Task Export_posts_target_and_ids_and_reads_the_results()
    {
        var handler = FakeHttpHandler.Json("""
            {"created": [{"item_id": "a1", "url": "https://x.test/1"}],
             "failed": [{"item_id": "a2", "error": "Already exported"}]}
            """);

        var result = await new EngineClient(handler.Client()).ExportActionItemsAsync(
            "20261015_202358", "azure_devops", ["a1", "a2"]);

        Assert.Equal([new CreatedTask("a1", "https://x.test/1")], result.Created);
        Assert.Equal([new FailedTask("a2", "Already exported")], result.Failed);
        var request = handler.Requests.Single();
        Assert.Equal((HttpMethod.Post, "/sessions/20261015_202358/action-items/export"), (request.Method, request.Path));
        Assert.Equal("""{"target":"azure_devops","item_ids":["a1","a2"]}""", request.Body);
    }

    [Fact]
    public async Task An_unconfigured_target_throws_the_engine_error()
    {
        var handler = FakeHttpHandler.Json(
            """{"error": {"code": "unknown_task_target", "message": "Not configured."}}""",
            HttpStatusCode.UnprocessableEntity);

        var error = await Assert.ThrowsAsync<EngineApiException>(
            () => new EngineClient(handler.Client()).ExportActionItemsAsync("s", "jira", ["a1"]));

        Assert.Equal(("unknown_task_target", "Not configured."), (error.Code, error.Message));
    }

    [Fact]
    public void Parser_reads_action_items_ready()
    {
        Assert.Equal(
            new ActionItemsReadyEvent("s1", 3),
            EngineEventParser.Parse("""{"type":"action_items_ready","session_id":"s1","data":{"session_id":"s1","count":3}}"""));
    }
}
