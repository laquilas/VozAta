using System.Collections.ObjectModel;
using System.Globalization;
using CommunityToolkit.Mvvm.ComponentModel;
using CommunityToolkit.Mvvm.Input;
using VozAta.Client;
using VozAta.Desktop.Services;

namespace VozAta.Desktop.ViewModels;

/// <summary>
/// The "Audio sources" tab of a recorded meeting (phase 66): every microphone and output the
/// recorder kept, ticked when it is used for the meeting. "Apply and regenerate" rebuilds the
/// meeting from the ticked ones (transcript, speakers and minutes again; edits are lost, so it
/// asks first); "Keep only the selected" deletes the files of the others.
/// </summary>
public sealed partial class MeetingSourcesViewModel(
    IEngineClient client,
    ILocalizationService localization,
    IDialogService? dialogs,
    string sessionId) : ObservableObject
{
    private HashSet<string> _applied = [];

    public ObservableCollection<MeetingSourceRow> Items { get; } = [];

    [ObservableProperty]
    public partial bool HasItems { get; private set; }

    /// <summary>"Kept until 19 Nov 2026" or "Kept until the meeting is deleted".</summary>
    [ObservableProperty]
    public partial string KeptText { get; private set; } = "";

    /// <summary>A short line after an action (or its error).</summary>
    [ObservableProperty]
    public partial string? Status { get; private set; }

    [ObservableProperty]
    [NotifyCanExecuteChangedFor(nameof(ApplyCommand), nameof(KeepSelectedCommand))]
    public partial bool IsBusy { get; private set; }

    /// <summary>The ticks differ from what the meeting uses now.</summary>
    public bool HasChanges => Items.Where(row => row.IsSelected).Select(row => row.Id).ToHashSet() is var ticked
        && ticked.Count > 0 && !ticked.SetEquals(_applied);

    public async Task LoadAsync(CancellationToken cancellationToken = default)
    {
        try
        {
            Show(await client.GetSessionSourcesAsync(sessionId, cancellationToken));
        }
        catch (Exception error) when (error is EngineApiException or EngineUnavailableException)
        {
            Show(new MeetingSources([], null)); // an older engine, or none kept: no tab
        }
    }

    [RelayCommand(CanExecute = nameof(CanApply))]
    private async Task ApplyAsync()
    {
        if (dialogs is not null && !await dialogs.ConfirmAsync(
                localization["SourcesApplyTitle"],
                localization["SourcesApplyMessage"],
                localization["SourcesApplyConfirm"],
                localization["MeetingDeleteCancel"]))
        {
            return;
        }

        var selected = Items.Where(row => row.IsSelected).Select(row => row.Id).ToList();
        await RunAsync(async () =>
        {
            await client.ChooseSessionSourcesAsync(sessionId, selected);
            _applied = [.. selected];
            Status = localization["SourcesApplied"];
            Refresh();
        });
    }

    [RelayCommand(CanExecute = nameof(CanKeepSelected))]
    private async Task KeepSelectedAsync()
    {
        await RunAsync(async () =>
        {
            var removed = await client.KeepSelectedSessionSourcesAsync(sessionId);
            Status = localization.Format("SourcesTrimmed", removed.Count);
            await LoadAsync();
        });
    }

    private bool CanApply() => !IsBusy && HasChanges;

    private bool CanKeepSelected() => !IsBusy && Items.Any(row => !row.IsSelected) && !HasChanges;

    private async Task RunAsync(Func<Task> action)
    {
        IsBusy = true;
        try
        {
            await action();
        }
        catch (EngineApiException error)
        {
            Status = error.Message;
        }
        catch (EngineUnavailableException)
        {
            Status = localization["EngineUnavailable"];
        }
        finally
        {
            IsBusy = false;
        }
    }

    private void Show(MeetingSources sources)
    {
        foreach (var row in Items)
        {
            row.PropertyChanged -= OnRowChanged;
        }

        Items.Clear();
        foreach (var source in sources.Items)
        {
            var row = new MeetingSourceRow(source, localization);
            row.PropertyChanged += OnRowChanged;
            Items.Add(row);
        }

        _applied = [.. sources.Items.Where(source => source.Selected).Select(source => source.Id)];
        HasItems = Items.Count > 0;
        KeptText = sources.KeptUntil is { } until
            ? localization.Format("SourcesKeptUntil", until.ToLocalTime().ToString("d", CultureInfo.CurrentCulture))
            : localization["SourcesKeptForever"];
        Refresh();
    }

    private void OnRowChanged(object? sender, System.ComponentModel.PropertyChangedEventArgs args)
    {
        if (args.PropertyName == nameof(MeetingSourceRow.IsSelected))
        {
            Refresh();
        }
    }

    private void Refresh()
    {
        OnPropertyChanged(nameof(HasChanges));
        ApplyCommand.NotifyCanExecuteChanged();
        KeepSelectedCommand.NotifyCanExecuteChanged();
    }
}

/// <summary>One kept source: ticked when the meeting uses it.</summary>
public sealed partial class MeetingSourceRow : ObservableObject
{
    public MeetingSourceRow(MeetingSource source, ILocalizationService localization)
    {
        Id = source.Id;
        Name = source.Name;
        IsSelected = source.Selected;
        Details = localization.Format(
            "SourceDetails",
            localization[source.Kind == "system" ? "SourceKindOutput" : "SourceKindInput"],
            TranscriptLine.FormatTime(source.DurationSeconds));
    }

    public string Id { get; }

    public string Name { get; }

    /// <summary>"Microphone · 00:42:10".</summary>
    public string Details { get; }

    [ObservableProperty]
    public partial bool IsSelected { get; set; }
}
