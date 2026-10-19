namespace VozAta.Client;

// Meetings by day (api-contract rows tagged 36): `GET /sessions?from=&to=` and `DELETE /sessions/{id}`.

/// <summary>
/// A meeting ZIP read back (phase 39): <see cref="Mode"/> is <c>imported</c> (a new meeting) or
/// <c>audio_restored</c> (the meeting was there without audio).
/// </summary>
public sealed record ImportedSession(string Id, string Mode)
{
    public bool AudioRestored => Mode == "audio_restored";
}

/// <summary>One local day: its meetings, newest first, and their total duration.</summary>
public sealed record SessionDay(DateOnly Date, double TotalSeconds, IReadOnlyList<SessionSummary> Items);

/// <summary>
/// The meetings of a date range grouped by local start day, newest first. <see cref="HasEarlier"/>
/// tells whether older meetings exist; <see cref="Storage"/> (<c>sqlite</c> | <c>files</c>) what a
/// delete does (permanent, or to the Recycle Bin).
/// </summary>
public sealed record SessionDays(
    IReadOnlyList<SessionDay> Days,
    double TotalSeconds,
    bool HasEarlier,
    string Storage = "files")
{
    /// <summary>Deleting a session of the file backend moves its folder to the Recycle Bin.</summary>
    public bool DeletesToRecycleBin => Storage == "files";
}
