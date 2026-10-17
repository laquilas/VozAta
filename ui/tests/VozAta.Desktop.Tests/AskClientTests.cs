using System.Net;
using VozAta.Client;
using VozAta.Desktop.Tests.Fakes;

namespace VozAta.Desktop.Tests;

public sealed class AskClientTests
{
    [Fact]
    public async Task Ask_posts_the_question_and_scope_and_reads_the_answer_id()
    {
        var handler = FakeHttpHandler.Json("""{"answer_id": "abc123"}""", HttpStatusCode.Accepted);

        var accepted = await new EngineClient(handler.Client()).AskAsync("Who owns it?", "20261015_202358");

        Assert.Equal("abc123", accepted.AnswerId);
        var request = handler.Requests.Single();
        Assert.Equal((HttpMethod.Post, "/ask"), (request.Method, request.Path));
        Assert.Equal("""{"question":"Who owns it?","session_id":"20261015_202358"}""", request.Body);
    }

    [Fact]
    public async Task Ask_without_a_session_asks_about_all_of_them()
    {
        var handler = FakeHttpHandler.Json("""{"answer_id": "abc123"}""", HttpStatusCode.Accepted);

        await new EngineClient(handler.Client()).AskAsync("q");

        Assert.Equal("""{"question":"q","session_id":null}""", handler.Requests.Single().Body);
    }

    [Fact]
    public async Task Ask_while_answering_throws_the_engine_error()
    {
        var handler = FakeHttpHandler.Json(
            """{"error": {"code": "answer_in_progress", "message": "Wait."}}""", HttpStatusCode.Conflict);

        var error = await Assert.ThrowsAsync<EngineApiException>(
            () => new EngineClient(handler.Client()).AskAsync("q"));

        Assert.Equal(("answer_in_progress", "Wait."), (error.Code, error.Message));
    }

    [Fact]
    public void Parser_reads_answer_chunks()
    {
        Assert.Equal(
            new AnswerChunkEvent(null, "a1", "Alice "),
            EngineEventParser.Parse("""{"type":"answer_chunk","session_id":null,"data":{"answer_id":"a1","text":"Alice "}}"""));
    }

    [Fact]
    public void Parser_reads_answer_done_with_citations_and_error()
    {
        var done = Assert.IsType<AnswerDoneEvent>(EngineEventParser.Parse("""
            {"type":"answer_done","session_id":"s1","data":{"answer_id":"a1",
             "citations":[{"session_id":"20261015_202358","segment_id":"mic-000001","start":83.4}],"error":null}}
            """));

        Assert.Equal(("s1", "a1", null), (done.SessionId, done.AnswerId, done.Error));
        Assert.Equal([new Citation("20261015_202358", "mic-000001", 83.4)], done.Citations);

        var failed = Assert.IsType<AnswerDoneEvent>(EngineEventParser.Parse(
            """{"type":"answer_done","session_id":null,"data":{"answer_id":"a2","citations":[],"error":"Ollama offline"}}"""));
        Assert.Equal("Ollama offline", failed.Error);
        Assert.Empty(failed.Citations);

        var noError = Assert.IsType<AnswerDoneEvent>(EngineEventParser.Parse(
            """{"type":"answer_done","session_id":null,"data":{"answer_id":"a3","citations":[]}}"""));
        Assert.Null(noError.Error);
    }

    [Theory]
    [InlineData("""{"type":"answer_chunk","session_id":null,"data":{"text":"x"}}""")]
    [InlineData("""{"type":"answer_done","session_id":null,"data":{"answer_id":"a1"}}""")]
    [InlineData("""{"type":"answer_done","session_id":null,"data":{"answer_id":"a1","citations":null}}""")]
    public void Parser_ignores_invalid_answer_events(string json)
    {
        Assert.Null(EngineEventParser.Parse(json));
    }
}
