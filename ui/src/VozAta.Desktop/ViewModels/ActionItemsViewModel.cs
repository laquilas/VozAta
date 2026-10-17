using System.Collections.ObjectModel;
using System.ComponentModel;
using CommunityToolkit.Mvvm.ComponentModel;
using CommunityToolkit.Mvvm.Input;
using VozAta.Client;
using VozAta.Desktop.Services;

namespace VozAta.Desktop.ViewModels;

/// <summary>An export target the engine has credentials for (<c>azure_devops</c>, <c>github</c>).</summary>
public sealed record TaskTargetOption(string Id, string Label)
{
    public override string ToString() => Label;
}

/// <summary>One action item in the checklist: editable until it is exported, then read-only with its link.</summary>
public sealed partial class ActionItemRow : ObservableObject
{
    public ActionItemRow(ActionItem item)
    {
        Id = item.Id;
        Description = item.Description;
        Owner = item.Owner ?? "";
        Due = item.Due ?? "";
        ExportedUrl = item.ExportedUrl;
    }

    public string Id { get; }

    [ObservableProperty]
    public partial string Description { get; set; }

    [ObservableProperty]
    public partial string Owner { get; set; }

    [ObservableProperty]
    public partial string Due { get; set; }

    /// <summary>Chosen for the next export (exported items cannot be chosen again).</summary>
    [ObservableProperty]
    public partial bool IsSelected { get; set; }

    [ObservableProperty]
    [NotifyPropertyChangedFor(nameof(IsExported), nameof(IsEditable))]
    public partial string? ExportedUrl { get; set; }

    /// <summary>Why the last export of this item failed (localized by the engine).</summary>
    [ObservableProperty]
    public partial string? Error { get; set; }

    public bool IsExported => ExportedUrl is not null;

    public bool IsEditable => !IsExported;

    public ActionItemEdit ToEdit() =>
        new(Id, Description.Trim(), Blank(Owner), Blank(Due));

    private static string? Blank(string text) => string.IsNullOrWhiteSpace(text) ? null : text.Trim();
}

/// <summary>
/// The "Action items" tab of a session (phase 23): a checklist with editable description, owner and
/// due date, an export target (only the configured ones) and the links of the created items.
/// Exported items are disabled, so nothing is exported twice.
/// </summary>
public sealed partial class ActionItemsViewModel(
    IEngineClient client, ILocalizationService localization, IShellService shell, string sessionId) : ObservableObject
{
    public ObservableCollection<ActionItemRow> Items { get; } = [];

    public ObservableCollection<TaskTargetOption> Targets { get; } = [];

    [ObservableProperty]
    [NotifyCanExecuteChangedFor(nameof(ExportCommand))]
    public partial TaskTargetOption? SelectedTarget { get; set; }

    [ObservableProperty]
    [NotifyPropertyChangedFor(nameof(IsEmpty))]
    public partial bool IsLoading { get; private set; }

    [ObservableProperty]
    [NotifyCanExecuteChangedFor(nameof(ExtractCommand), nameof(ExportCommand))]
    public partial bool IsExtracting { get; private set; }

    [ObservableProperty]
    [NotifyCanExecuteChangedFor(nameof(ExtractCommand), nameof(ExportCommand))]
    public partial bool IsExporting { get; private set; }

    /// <summary>The session still records: action items come once it stops.</summary>
    [ObservableProperty]
    [NotifyCanExecuteChangedFor(nameof(ExtractCommand))]
    public partial bool IsLive { get; set; }

    [ObservableProperty]
    public partial string? Error { get; private set; }

    [ObservableProperty]
    public partial string? Message { get; private set; }

    [ObservableProperty]
    [NotifyPropertyChangedFor(nameof(IsEmpty))]
    public partial bool HasItems { get; private set; }

    [ObservableProperty]
    public partial bool HasTargets { get; private set; }

    public bool IsEmpty => !IsLoading && !HasItems;

    public async Task LoadAsync(CancellationToken cancellationToken = default)
    {
        IsLoading = true;
        Error = null;
        try
        {
            Show(await client.GetActionItemsAsync(sessionId, cancellationToken));
        }
        catch (Exception error) when (error is EngineApiException or EngineUnavailableException)
        {
            Error = ErrorText(error);
        }
        finally
        {
            IsLoading = false;
        }
    }

    private bool CanExtract() => !IsLive && !IsExtracting && !IsExporting;

    /// <summary>Ask the engine to extract again; the list reloads on <c>action_items_ready</c>.</summary>
    [RelayCommand(CanExecute = nameof(CanExtract))]
    private async Task ExtractAsync()
    {
        Error = Message = null;
        IsExtracting = true;
        try
        {
            await client.ExtractActionItemsAsync(sessionId);
        }
        catch (Exception error) when (error is EngineApiException or EngineUnavailableException)
        {
            IsExtracting = false;
            Error = ErrorText(error);
        }
    }

    private bool CanExport() =>
        !IsExporting && !IsExtracting && SelectedTarget is not null && Items.Any(row => row.IsSelected && !row.IsExported);

    /// <summary>Save the edits, then export the selected items to the chosen target.</summary>
    [RelayCommand(CanExecute = nameof(CanExport))]
    private async Task ExportAsync()
    {
        Error = Message = null;
        IsExporting = true;
        var selected = Items.Where(row => row.IsSelected && !row.IsExported).Select(row => row.Id).ToList();
        foreach (var row in Items)
        {
            row.Error = null;
        }

        try
        {
            var edits = Items.Where(row => row.IsEditable).Select(row => row.ToEdit()).ToList();
            if (edits.Count > 0)
            {
                Show(await client.UpdateActionItemsAsync(sessionId, edits), selected);
            }

            var result = await client.ExportActionItemsAsync(sessionId, SelectedTarget!.Id, selected);
            Apply(result);
        }
        catch (Exception error) when (error is EngineApiException or EngineUnavailableException)
        {
            Error = ErrorText(error);
        }
        finally
        {
            IsExporting = false;
        }
    }

    /// <summary>Open a created work item / issue in the browser.</summary>
    [RelayCommand]
    private void OpenLink(string? url)
    {
        if (!string.IsNullOrEmpty(url))
        {
            shell.Open(url);
        }
    }

    /// <summary>An <c>action_items_ready</c> event: reload when it is ours.</summary>
    public async Task OnReadyAsync(string? id)
    {
        if (id != sessionId)
        {
            return;
        }

        IsExtracting = false;
        await LoadAsync();
    }

    /// <summary>An <c>error</c> event: ends our extraction with the engine's message.</summary>
    public void OnError(string? id, string message)
    {
        if (id == sessionId && IsExtracting)
        {
            IsExtracting = false;
            Error = message;
        }
    }

    private void Apply(ActionItemsExportResult result)
    {
        foreach (var created in result.Created)
        {
            if (Find(created.ItemId) is { } row)
            {
                row.ExportedUrl = created.Url;
                row.IsSelected = false;
            }
        }

        foreach (var failed in result.Failed)
        {
            if (Find(failed.ItemId) is { } row)
            {
                row.Error = failed.Error;
            }
        }

        Message = result.Created.Count > 0 ? localization.Format("ActionItemsExported", result.Created.Count) : null;
        Error = result.Failed.Count > 0 ? localization.Format("ActionItemsExportFailed", result.Failed.Count) : null;
        ExportCommand.NotifyCanExecuteChanged();
    }

    private void Show(ActionItemList list, IReadOnlyCollection<string>? selected = null)
    {
        foreach (var row in Items)
        {
            row.PropertyChanged -= OnRowChanged;
        }

        Items.Clear();
        foreach (var item in list.Items)
        {
            var row = new ActionItemRow(item) { IsSelected = selected?.Contains(item.Id) == true && item.ExportedUrl is null };
            row.PropertyChanged += OnRowChanged;
            Items.Add(row);
        }

        var keep = SelectedTarget?.Id;
        Targets.Clear();
        foreach (var target in list.Targets)
        {
            Targets.Add(new TaskTargetOption(target, localization[$"TaskTarget_{target}"]));
        }

        SelectedTarget = Targets.FirstOrDefault(target => target.Id == keep) ?? Targets.FirstOrDefault();
        HasItems = Items.Count > 0;
        HasTargets = Targets.Count > 0;
        ExportCommand.NotifyCanExecuteChanged();
    }

    private void OnRowChanged(object? sender, PropertyChangedEventArgs args)
    {
        if (args.PropertyName == nameof(ActionItemRow.IsSelected))
        {
            ExportCommand.NotifyCanExecuteChanged();
        }
    }

    private ActionItemRow? Find(string id) => Items.FirstOrDefault(row => row.Id == id);

    private string ErrorText(Exception error) =>
        error is EngineUnavailableException ? localization["EngineUnavailable"] : error.Message;
}
