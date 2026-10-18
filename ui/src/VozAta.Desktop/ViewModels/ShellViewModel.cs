using System.ComponentModel;
using CommunityToolkit.Mvvm.ComponentModel;
using CommunityToolkit.Mvvm.Input;
using VozAta.Desktop.Services;

namespace VozAta.Desktop.ViewModels;

/// <summary>One entry of the sidebar: a page, its label, icon and keyboard shortcut.</summary>
public sealed partial class NavItem(string key, string labelKey, string icon, string gesture, object page)
    : ObservableObject
{
    /// <summary>The <c>NavigateCommand</c> parameter: <c>recorder</c>, <c>meetings</c>, <c>ask</c>, <c>config</c>.</summary>
    public string Key { get; } = key;

    public string LabelKey { get; } = labelKey;

    /// <summary>The icon resource (<c>Icon.*</c> in Icons.axaml).</summary>
    public string Icon { get; } = icon;

    /// <summary>The keyboard shortcut, e.g. <c>Ctrl+1</c>.</summary>
    public string Gesture { get; } = gesture;

    /// <summary>The page ViewModel the content area shows.</summary>
    public object Page { get; } = page;

    [ObservableProperty]
    public partial string Label { get; private set; } = labelKey;

    /// <summary>Selected in the sidebar.</summary>
    [ObservableProperty]
    public partial bool IsCurrent { get; set; }

    public void Refresh(ILocalizationService localization) => Label = localization[LabelKey];
}

/// <summary>
/// The Toggl-style shell (phase 35): a collapsible sidebar with the pages and the recording
/// indicator, and the current page. It starts on the Recorder; Ctrl+1…4 switch pages.
/// </summary>
public sealed partial class ShellViewModel : ObservableObject, IDisposable
{
    public const string Recorder = "recorder";
    public const string Meetings = "meetings";
    public const string Ask = "ask";
    public const string Config = "config";

    private readonly ILocalizationService _localization;
    private readonly IUiPreferences _preferences;
    private readonly bool _ready; // the saved collapse state is applied without saving it again

    public ShellViewModel(
        RecorderPageViewModel recorder,
        MeetingsPageViewModel meetings,
        AskPageViewModel ask,
        ConfigPageViewModel config,
        RecordingSessionService session,
        ILocalizationService localization,
        IUiPreferences preferences)
    {
        _localization = localization;
        _preferences = preferences;
        Session = session;
        Pages =
        [
            new(Recorder, "NavRecorder", "Icon.Record", "Ctrl+1", recorder),
            new(Meetings, "NavMeetings", "Icon.History", "Ctrl+2", meetings),
            new(Ask, "NavAsk", "Icon.Chat", "Ctrl+3", ask),
            new(Config, "NavConfig", "Icon.Settings", "Ctrl+4", config),
        ];
        IsCollapsed = preferences.Load().SidebarCollapsed;
        CurrentItem = Pages[0];
        session.PropertyChanged += OnSessionChanged;
        RefreshTexts();
        _ready = true;
    }

    public IReadOnlyList<NavItem> Pages { get; }

    /// <summary>The recording shown in the sidebar on every page.</summary>
    public RecordingSessionService Session { get; }

    [ObservableProperty]
    [NotifyPropertyChangedFor(nameof(CurrentPage), nameof(IsRecordingElsewhere))]
    public partial NavItem CurrentItem { get; private set; }

    /// <summary>The page ViewModel shown in the content area (a DataTemplate per type).</summary>
    public object CurrentPage => SessionPage ?? CurrentItem.Page;

    /// <summary>A meeting open as its own page (phase 37) over the Meetings entry; null when none.</summary>
    [ObservableProperty]
    [NotifyPropertyChangedFor(nameof(CurrentPage))]
    public partial object? SessionPage { get; private set; }

    /// <summary>The user went to another page (or back to the list) while a meeting page was open.</summary>
    public event EventHandler? SessionLeft;

    /// <summary>Show a meeting page (the Meetings entry stays selected in the sidebar).</summary>
    public void OpenSession(object page)
    {
        CurrentItem = Pages.First(item => item.Key == Meetings);
        SessionPage = page;
    }

    /// <summary>The meeting page closed (back, deleted): the Meetings list shows again.</summary>
    public void CloseSession() => SessionPage = null;

    /// <summary>The sidebar shows icons only (remembered in <c>ui.json</c>).</summary>
    [ObservableProperty]
    [NotifyPropertyChangedFor(nameof(IsExpanded), nameof(ToggleSidebarText))]
    public partial bool IsCollapsed { get; set; }

    public bool IsExpanded => !IsCollapsed;

    public string ToggleSidebarText => _localization[IsCollapsed ? "SidebarExpand" : "SidebarCollapse"];

    /// <summary>A recording runs while another page is shown: the banner over the page links back.</summary>
    public bool IsRecordingElsewhere => Session.IsRecording && CurrentItem.Key != Recorder;

    /// <summary>"Recording 00:12:03 — open the recorder".</summary>
    public string RecordingBannerText => _localization.Format("GoToRecorder", Session.Elapsed);

    /// <summary>Show a page by key (<see cref="NavItem.Key"/>); unknown keys are ignored.</summary>
    [RelayCommand]
    private void Navigate(string? key)
    {
        if (Pages.FirstOrDefault(item => item.Key == key) is { } item)
        {
            CurrentItem = item;
            if (SessionPage is not null)
            {
                SessionPage = null;
                SessionLeft?.Invoke(this, EventArgs.Empty);
            }
        }
    }

    [RelayCommand]
    private void ToggleSidebar() => IsCollapsed = !IsCollapsed;

    public void RefreshTexts()
    {
        foreach (var item in Pages)
        {
            item.Refresh(_localization);
        }

        OnPropertyChanged(nameof(ToggleSidebarText));
        OnPropertyChanged(nameof(RecordingBannerText));
    }

    public void Dispose() => Session.PropertyChanged -= OnSessionChanged;

    partial void OnCurrentItemChanged(NavItem oldValue, NavItem newValue)
    {
        if (oldValue is not null) // null on the first page
        {
            oldValue.IsCurrent = false;
        }

        newValue.IsCurrent = true;
    }

    partial void OnIsCollapsedChanged(bool value)
    {
        if (_ready)
        {
            _preferences.Save(_preferences.Load() with { SidebarCollapsed = value });
        }
    }

    private void OnSessionChanged(object? sender, PropertyChangedEventArgs args)
    {
        switch (args.PropertyName)
        {
            case nameof(RecordingSessionService.State):
                OnPropertyChanged(nameof(IsRecordingElsewhere));
                break;
            case nameof(RecordingSessionService.Elapsed):
                OnPropertyChanged(nameof(RecordingBannerText));
                break;
        }
    }
}
