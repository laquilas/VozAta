using VozAta.Client;
using VozAta.Desktop.Tests.Fakes;

namespace VozAta.Desktop.Tests;

/// <summary>The folder import of phase 33 in the client: <c>GET /migration</c> and its events.</summary>
public sealed class MigrationClientTests
{
    [Fact]
    public async Task Get_migration_reads_the_summary_and_the_errors()
    {
        var handler = FakeHttpHandler.Json("""
            {"state": "no_space", "done": 2, "total": 5, "current": null, "paused": false,
             "imported": 1, "skipped": 1, "needed_bytes": 2048, "free_bytes": 1024,
             "message": "Not enough space",
             "errors": [{"folder": "C:/rec/20261015_202358", "reason": "unreadable_wav",
                         "message": "An audio file could not be read.", "detail": "mic.wav: bad"}]}
            """);

        var summary = await new EngineClient(handler.Client()).GetMigrationAsync();

        Assert.Equal((HttpMethod.Get, "/migration"), (handler.Requests.Single().Method, handler.Requests.Single().Path));
        Assert.Equal(("no_space", 2, 5, 1, 1), (summary.State, summary.Done, summary.Total, summary.Imported, summary.Skipped));
        Assert.Equal((2048L, 1024L, "Not enough space"), (summary.NeededBytes!.Value, summary.FreeBytes!.Value, summary.Message));
        Assert.False(summary.IsRunning);
        Assert.Equal(
            new MigrationFolderError("C:/rec/20261015_202358", "unreadable_wav", "An audio file could not be read.", "mic.wav: bad"),
            Assert.Single(summary.Errors));
    }

    [Fact]
    public void Parser_reads_the_migration_events()
    {
        var progress = EngineEventParser.Parse(
            """{"type":"migration_progress","session_id":null,"data":{"done":1,"total":3,"current":"20261015_202358","paused":true}}""");
        var done = EngineEventParser.Parse(
            """{"type":"migration_done","session_id":null,"data":{"state":"done","imported":2,"skipped":1,"errors":1}}""");

        Assert.Equal(new MigrationProgressEvent(null, 1, 3, "20261015_202358", true), progress);
        Assert.Equal(new MigrationDoneEvent(null, "done", 2, 1, 1), done);
    }
}
