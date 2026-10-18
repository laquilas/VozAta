using VozAta.Client;

namespace VozAta.Desktop.Tests.Fakes;

/// <summary>Meetings by day (phase 36): <see cref="Sessions"/> grouped by local start day, deletes recorded.</summary>
internal sealed partial class FakeEngineClient
{
    /// <summary>What <see cref="SessionDays.Storage"/> answers: <c>files</c> or <c>sqlite</c>.</summary>
    public string Storage { get; set; } = "files";

    public List<(DateOnly First, DateOnly Last)> DayRequests { get; } = [];

    public List<string> Deleted { get; } = [];

    public Exception? DaysError { get; set; }

    public Exception? DeleteError { get; set; }

    /// <summary>When set, range requests wait for it (tests check what shows while loading).</summary>
    public TaskCompletionSource? DaysGate { get; set; }

    public async Task<SessionDays> ListSessionDaysAsync(
        DateOnly first, DateOnly last, CancellationToken cancellationToken = default)
    {
        Calls.Add($"days {first:yyyy-MM-dd} {last:yyyy-MM-dd}");
        DayRequests.Add((first, last));
        if (DaysGate is { } gate)
        {
            await gate.Task;
        }

        if (DaysError is not null)
        {
            throw DaysError;
        }

        var days = Sessions
            .Where(session => Day(session) is { } day && day >= first && day <= last)
            .OrderByDescending(session => session.StartedAt)
            .GroupBy(session => Day(session)!.Value)
            .OrderByDescending(group => group.Key)
            .Select(group => new SessionDay(group.Key, group.Sum(item => item.DurationSeconds ?? 0), [.. group]))
            .ToList();
        var earlier = Sessions.Any(session => Day(session) is { } day && day < first);
        return new SessionDays(days, days.Sum(day => day.TotalSeconds), earlier, Storage);
    }

    public Task DeleteSessionAsync(string id, CancellationToken cancellationToken = default)
    {
        Calls.Add($"delete {id}");
        if (DeleteError is not null)
        {
            return Task.FromException(DeleteError);
        }

        Deleted.Add(id);
        Sessions.RemoveAll(session => session.Id == id);
        return Task.CompletedTask;
    }

    private static DateOnly? Day(SessionSummary session) =>
        session.StartedAt is { } start ? DateOnly.FromDateTime(start.ToLocalTime().DateTime) : null;
}
