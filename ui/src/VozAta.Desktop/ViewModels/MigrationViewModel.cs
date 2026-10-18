using System.Collections.ObjectModel;
using CommunityToolkit.Mvvm.ComponentModel;
using CommunityToolkit.Mvvm.Input;
using VozAta.Client;
using VozAta.Desktop.Services;

namespace VozAta.Desktop.ViewModels;

/// <summary>
/// The import of the meeting folders recorded before the database (phase 33): a banner with
/// "Importing old meetings… N of M" and a progress bar while it runs, then the counts with
/// "Show errors" (folders not imported, with the reason) until dismissed. The meetings list
/// reloads when it ends.
/// </summary>
public sealed partial class MigrationViewModel(
    IEngineClient client,
    ILocalizationService localization,
    Func<Task> meetingsChanged) : ObservableObject
{
    private MigrationSummary? _summary;
    private bool _seenRunning; // the import ran while this app watched (so its end is news)

    public ObservableCollection<MigrationFolderError> Errors { get; } = [];

    [ObservableProperty]
    public partial bool IsRunning { get; private set; }

    [ObservableProperty]
    public partial int Done { get; private set; }

    [ObservableProperty]
    public partial int Total { get; private set; }

    [ObservableProperty]
    public partial bool IsPaused { get; private set; }

    /// <summary>The end of the import is shown (counts, a failure or a full disk).</summary>
    [ObservableProperty]
    public partial bool IsFinished { get; private set; }

    [ObservableProperty]
    public partial bool HasErrors { get; private set; }

    [ObservableProperty]
    public partial bool ErrorsOpen { get; private set; }

    [ObservableProperty]
    public partial string Text { get; private set; } = "";

    public bool IsVisible => IsRunning || IsFinished;

    public double Progress => Total == 0 ? 0 : 100.0 * Done / Total;

    /// <summary>On (re)connect: the import may have run, or ended, before the events arrived.</summary>
    public async Task RefreshAsync(CancellationToken cancellationToken = default)
    {
        MigrationSummary summary;
        try
        {
            summary = await client.GetMigrationAsync(cancellationToken);
        }
        catch (Exception error) when (error is EngineApiException or EngineUnavailableException)
        {
            return; // an engine without the import (or gone): nothing to show
        }

        _summary = summary;
        if (summary.IsRunning)
        {
            ShowProgress(summary.Done, summary.Total, summary.Paused);
        }
        else if (summary.State is "no_space" or "failed" || summary.State == "done" && (_seenRunning || summary.Imported > 0))
        {
            await FinishAsync(summary);
        }
    }

    public void OnProgress(MigrationProgressEvent progress) =>
        ShowProgress(progress.Done, progress.Total, progress.Paused);

    public Task OnDoneAsync(MigrationDoneEvent done) => RefreshAsync();

    /// <summary>The engine went away: hide the progress (a restarted engine reports it again).</summary>
    public void OnConnectionLost()
    {
        IsRunning = false;
        OnPropertyChanged(nameof(IsVisible));
    }

    [RelayCommand]
    private void ShowErrors() => ErrorsOpen = true;

    [RelayCommand]
    private void CloseErrors() => ErrorsOpen = false;

    [RelayCommand]
    private void Dismiss()
    {
        IsFinished = false;
        ErrorsOpen = false;
        OnPropertyChanged(nameof(IsVisible));
    }

    public void RefreshTexts()
    {
        if (IsRunning)
        {
            Text = localization.Format(IsPaused ? "MigrationPaused" : "MigrationProgress", Done, Total);
        }
        else if (_summary is { } summary)
        {
            Text = summary.State switch
            {
                "no_space" => summary.Message ?? localization["MigrationFailed"],
                "failed" => localization["MigrationFailed"],
                _ => localization.Format("MigrationDone", summary.Imported, Errors.Count),
            };
        }
    }

    private void ShowProgress(int done, int total, bool paused)
    {
        _seenRunning = true;
        Done = done;
        Total = total;
        IsPaused = paused;
        IsRunning = true;
        IsFinished = false;
        RefreshTexts();
        OnPropertyChanged(nameof(Progress));
        OnPropertyChanged(nameof(IsVisible));
    }

    private async Task FinishAsync(MigrationSummary summary)
    {
        var imported = summary.Imported > 0;
        IsRunning = false;
        Errors.Clear();
        foreach (var error in summary.Errors)
        {
            Errors.Add(error);
        }

        HasErrors = Errors.Count > 0;
        IsFinished = true;
        _seenRunning = false;
        RefreshTexts();
        OnPropertyChanged(nameof(IsVisible));
        if (imported)
        {
            await meetingsChanged();
        }
    }
}
