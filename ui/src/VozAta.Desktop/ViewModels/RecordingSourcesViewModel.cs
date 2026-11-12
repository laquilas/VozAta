using System.Collections.ObjectModel;
using CommunityToolkit.Mvvm.ComponentModel;
using CommunityToolkit.Mvvm.Input;
using VozAta.Client;
using VozAta.Desktop.Services;

namespace VozAta.Desktop.ViewModels;

/// <summary>
/// The audio sources of the recording (phase 65): every microphone and output the recorder
/// records, which ones are mixed into the meeting, and the Auto / On / Off choice of each.
/// Fed by the recorder's <c>sources</c> event; a choice goes to the recorder at once.
/// </summary>
public sealed partial class RecordingSourcesViewModel : ObservableObject
{
    private readonly IRecorderClient? _recorder;
    private readonly ILocalizationService _localization;
    private readonly Action<string> _notify;

    public RecordingSourcesViewModel(IRecorderClient? recorder, ILocalizationService localization, Action<string> notify)
    {
        _recorder = recorder;
        _localization = localization;
        _notify = notify;
        Items.CollectionChanged += (_, _) => OnPropertyChanged(nameof(HasItems));
    }

    public ObservableCollection<SourceRowViewModel> Items { get; } = [];

    public bool HasItems => Items.Count > 0;

    /// <summary>"3 of 5 in use": the chip's text.</summary>
    [ObservableProperty]
    public partial string Summary { get; private set; } = "";

    /// <summary>Every open source gives only silence: the recording would be empty.</summary>
    [ObservableProperty]
    public partial bool AllSilent { get; private set; }

    /// <summary>The recorder's list: rows are kept (by id) so the flyout does not flicker.</summary>
    public void Update(RecordingSources sources)
    {
        var ids = sources.Items.Select(item => item.Id).ToHashSet();
        for (var i = Items.Count - 1; i >= 0; i--)
        {
            if (!ids.Contains(Items[i].Id))
            {
                Items.RemoveAt(i);
            }
        }

        for (var index = 0; index < sources.Items.Count; index++)
        {
            var item = sources.Items[index];
            var row = Items.FirstOrDefault(existing => existing.Id == item.Id);
            if (row is null)
            {
                row = new SourceRowViewModel(item.Id, SetModeAsync);
                Items.Insert(Math.Min(index, Items.Count), row);
            }

            row.Apply(item, _localization);
        }

        RefreshSummary();
    }

    public void Clear()
    {
        Items.Clear();
        RefreshSummary();
    }

    public void RefreshTexts()
    {
        foreach (var row in Items)
        {
            row.RefreshTexts(_localization);
        }

        RefreshSummary();
    }

    private async Task SetModeAsync(SourceRowViewModel row, string mode)
    {
        if (_recorder is null)
        {
            return;
        }

        try
        {
            Update(await _recorder.SetSourceModeAsync(row.Id, mode));
        }
        catch (Exception error) when (error is EngineApiException or EngineUnavailableException)
        {
            _notify(_localization.Format("SourceModeFailed", row.Name, error.Message));
        }
    }

    private void RefreshSummary()
    {
        var open = Items.Where(row => !row.HasFailed).ToList();
        Summary = _localization.Format("SourcesSummary", Items.Count(row => row.IsSelected), Items.Count);
        AllSilent = open.Count > 0 && open.All(row => row.IsSilent);
    }
}

/// <summary>One source in the list: its level, whether it is mixed, and its mode.</summary>
public sealed partial class SourceRowViewModel(string id, Func<SourceRowViewModel, string, Task> setMode) : ObservableObject
{
    public string Id { get; } = id;

    [ObservableProperty]
    public partial string Name { get; private set; } = "";

    /// <summary>A loopback (what an output plays) rather than a microphone.</summary>
    [ObservableProperty]
    public partial bool IsOutput { get; private set; }

    [ObservableProperty]
    [NotifyPropertyChangedFor(nameof(IsAuto), nameof(IsOn), nameof(IsOff))]
    public partial string Mode { get; private set; } = "auto";

    [ObservableProperty]
    public partial bool IsSelected { get; private set; }

    [ObservableProperty]
    public partial bool IsPreferred { get; private set; }

    [ObservableProperty]
    public partial bool IsSilent { get; private set; }

    [ObservableProperty]
    public partial bool HasFailed { get; private set; }

    /// <summary>0…1 for −60…0 dBFS, like the channel meters.</summary>
    [ObservableProperty]
    public partial double Level { get; private set; }

    [ObservableProperty]
    public partial string KindText { get; private set; } = "";

    [ObservableProperty]
    public partial string StatusText { get; private set; } = "";

    [ObservableProperty]
    public partial string AutoText { get; private set; } = "";

    [ObservableProperty]
    public partial string OnText { get; private set; } = "";

    [ObservableProperty]
    public partial string OffText { get; private set; } = "";

    private string? _error;

    public bool IsAuto => Mode == "auto";

    public bool IsOn => Mode == "on";

    public bool IsOff => Mode == "off";

    public void Apply(RecordingSource source, ILocalizationService localization)
    {
        Name = source.Name;
        IsOutput = source.Kind == "system";
        Mode = source.Mode;
        IsSelected = source.Selected;
        IsPreferred = source.Preferred;
        IsSilent = source.Silent;
        HasFailed = source.State == "failed";
        _error = source.Error;
        Level = LevelMeterViewModel.Normalize(source.RmsDb);
        RefreshTexts(localization);
    }

    public void RefreshTexts(ILocalizationService localization)
    {
        KindText = localization[IsOutput ? "SourceKindOutput" : "SourceKindInput"];
        StatusText = HasFailed
            ? localization.Format("SourceFailed", _error ?? "")
            : IsSilent
                ? localization["SourceSilent"]
                : IsSelected ? localization["SourceInUse"] : localization["SourceNotInUse"];
        AutoText = localization["SourceModeAuto"];
        OnText = localization["SourceModeOn"];
        OffText = localization["SourceModeOff"];
    }

    [RelayCommand]
    private Task SetAuto() => setMode(this, "auto");

    [RelayCommand]
    private Task SetOn() => setMode(this, "on");

    [RelayCommand]
    private Task SetOff() => setMode(this, "off");
}
