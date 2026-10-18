using System.Collections.ObjectModel;
using CommunityToolkit.Mvvm.ComponentModel;
using CommunityToolkit.Mvvm.Input;
using VozAta.Client;
using VozAta.Desktop.Services;

namespace VozAta.Desktop.ViewModels;

/// <summary>An interrupted session offered for recovery: start date and recorded length.</summary>
public sealed record RecoverySession(string Id, string Started, string Duration);

/// <summary>
/// Crash recovery dialog (phase 17): lists the sessions of a <c>recovery_available</c> event with
/// "Recover" and "Later". The engine recovers one session at a time, so "Recover" queues them and
/// starts the next one when the current one reports <c>done</c> (or fails).
/// </summary>
public sealed partial class RecoveryViewModel(
    IEngineClient client,
    ILocalizationService localization,
    Action<string> notify) : ObservableObject
{
    private readonly HashSet<string> _offered = [];
    private readonly Queue<string> _queue = new();
    private readonly Dictionary<string, string> _labels = [];

    public ObservableCollection<RecoverySession> Sessions { get; } = [];

    [ObservableProperty]
    public partial bool IsOpen { get; private set; }

    /// <summary>The session the engine is recovering right now (null when none).</summary>
    public string? Recovering { get; private set; }

    /// <summary>Add the offered sessions (described by <c>GET /sessions/{id}</c>) and open the dialog.</summary>
    public async Task OfferAsync(IReadOnlyList<string> sessionIds, CancellationToken cancellationToken = default)
    {
        foreach (var id in sessionIds)
        {
            if (id == Recovering || _queue.Contains(id) || !_offered.Add(id))
            {
                continue;
            }

            var session = await DescribeAsync(id, cancellationToken);
            _labels[id] = session.Started;
            Sessions.Add(session);
            IsOpen = true;
        }
    }

    [RelayCommand]
    private async Task RecoverAsync()
    {
        foreach (var session in Sessions)
        {
            _queue.Enqueue(session.Id);
        }

        Close();
        await RecoverNextAsync();
    }

    /// <summary>Close without recovering; the engine offers the sessions again on the next start.</summary>
    [RelayCommand]
    private void Later() => Close();

    /// <summary>A <c>status</c> event: the session being recovered finished, so the next one starts.</summary>
    public Task OnStatusAsync(StatusEvent status)
    {
        if (Recovering is null || status.SessionId != Recovering || status.Status is not ("done" or "interrupted"))
        {
            return Task.CompletedTask;
        }

        if (status.Status == "done")
        {
            notify(localization.Format("SessionRecovered", _labels.GetValueOrDefault(Recovering, Recovering)));
        }

        Recovering = null;
        return RecoverNextAsync();
    }

    /// <summary>An <c>error</c> event: a failed recovery (already shown as a notification) moves on.</summary>
    public Task OnErrorAsync(ErrorEvent error)
    {
        if (Recovering is null || error.SessionId != Recovering || error.Code != "recovery_failed")
        {
            return Task.CompletedTask;
        }

        Recovering = null;
        return RecoverNextAsync();
    }

    /// <summary>The engine went away: forget everything; it offers the sessions again once back.</summary>
    public void OnConnectionLost()
    {
        Recovering = null;
        _queue.Clear();
        Close();
    }

    private void Close()
    {
        Sessions.Clear();
        _offered.Clear();
        IsOpen = false;
    }

    private async Task RecoverNextAsync()
    {
        while (Recovering is null && _queue.TryDequeue(out var id))
        {
            Recovering = id; // status events may arrive before the HTTP answer
            try
            {
                await client.RecoverSessionAsync(id);
            }
            catch (Exception error) when (error is EngineApiException or EngineUnavailableException)
            {
                Recovering = null;
                notify(error is EngineUnavailableException ? localization["EngineUnavailable"] : error.Message);
            }
        }
    }

    private async Task<RecoverySession> DescribeAsync(string id, CancellationToken cancellationToken)
    {
        try
        {
            var detail = await client.GetSessionAsync(id, cancellationToken);
            return new RecoverySession(
                id,
                SessionPageViewModel.FormatStart(detail.StartedAt) ?? id,
                TranscriptLine.FormatTime(detail.DurationSeconds ?? 0));
        }
        catch (Exception error) when (error is EngineApiException or EngineUnavailableException)
        {
            return new RecoverySession(id, id, "");
        }
    }
}
