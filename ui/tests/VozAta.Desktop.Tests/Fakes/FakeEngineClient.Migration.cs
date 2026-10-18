using VozAta.Client;

namespace VozAta.Desktop.Tests.Fakes;

/// <summary>Folder import (phase 33): a scripted <c>GET /migration</c>.</summary>
internal sealed partial class FakeEngineClient
{
    public static readonly MigrationSummary MigrationDisabled =
        new("disabled", 0, 0, null, false, 0, 0, null, null, null, []);

    public MigrationSummary Migration { get; set; } = MigrationDisabled;

    public Exception? MigrationError { get; set; }

    public Task<MigrationSummary> GetMigrationAsync(CancellationToken cancellationToken = default)
    {
        Calls.Add("migration");
        return MigrationError is null ? Task.FromResult(Migration) : Task.FromException<MigrationSummary>(MigrationError);
    }
}
