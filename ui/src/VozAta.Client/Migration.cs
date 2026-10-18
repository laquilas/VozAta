namespace VozAta.Client;

// Folder import (api-contract rows tagged 33): `GET /migration`, `migration_progress`, `migration_done`.

/// <summary>A folder that was not imported: <see cref="Message"/> is localized by the engine.</summary>
public sealed record MigrationFolderError(string Folder, string Reason, string Message, string Detail);

/// <summary>
/// The import of the meeting folders recorded before the database. <see cref="State"/>:
/// <c>disabled</c> (file backend) | <c>idle</c> | <c>running</c> | <c>done</c> | <c>no_space</c> |
/// <c>failed</c>; <see cref="Message"/> explains <c>no_space</c>.
/// </summary>
public sealed record MigrationSummary(
    string State,
    int Done,
    int Total,
    string? Current,
    bool Paused,
    int Imported,
    int Skipped,
    long? NeededBytes,
    long? FreeBytes,
    string? Message,
    IReadOnlyList<MigrationFolderError> Errors)
{
    public bool IsRunning => State == "running";
}

/// <summary>The import moved on to the next folder (or paused while a meeting records).</summary>
public sealed record MigrationProgressEvent(string? SessionId, int Done, int Total, string? Current, bool Paused)
    : EngineEvent(SessionId);

/// <summary>The import ended: <see cref="Errors"/> counts every folder recorded as not imported.</summary>
public sealed record MigrationDoneEvent(string? SessionId, string State, int Imported, int Skipped, int Errors)
    : EngineEvent(SessionId);
