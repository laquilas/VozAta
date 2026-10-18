using System.Collections.ObjectModel;
using CommunityToolkit.Mvvm.ComponentModel;
using VozAta.Desktop.Services;

namespace VozAta.Desktop.ViewModels;

/// <summary>What a Config section shows on the right.</summary>
public enum ConfigSectionKind
{
    /// <summary>The engine keys of one <c>GET /settings</c> group.</summary>
    Engine,
    Desktop,
    Vocabulary,
    Storage,
    About,
}

/// <summary>One entry of the Config page's section list.</summary>
public sealed partial class ConfigSection(string id, ConfigSectionKind kind, SettingGroupViewModel? group = null)
    : ObservableObject
{
    public string Id { get; } = id;

    public ConfigSectionKind Kind { get; } = kind;

    /// <summary>The engine group (null for the app's own sections).</summary>
    public SettingGroupViewModel? Group { get; } = group;

    [ObservableProperty]
    public partial string Title { get; private set; } = id;

    /// <summary>Kept by the search box: a matching key, or a matching title for the app's sections.</summary>
    [ObservableProperty]
    public partial bool IsVisible { get; set; } = true;

    public void Refresh(ILocalizationService localization) =>
        Title = Group?.Title ?? localization[$"ConfigSection_{Id}"];

    public override string ToString() => Title;
}

/// <summary>
/// The Config page (phase 38): a section list (the engine groups, then Desktop app, Vocabulary,
/// Storage and About), a search box that filters keys by label, key name and help text across
/// sections, and the editors of the selected section. Editors stay generated from
/// <c>GET /settings</c>; the engine's <c>.env</c> stays the source.
/// </summary>
public sealed partial class ConfigPageViewModel : ObservableObject
{
    private static readonly (string Id, ConfigSectionKind Kind)[] AppSections =
    [
        ("desktop", ConfigSectionKind.Desktop),
        ("vocabulary", ConfigSectionKind.Vocabulary),
        ("storage", ConfigSectionKind.Storage),
        ("about", ConfigSectionKind.About),
    ];

    private readonly ILocalizationService _localization;
    private bool _rebuilding; // the section list is being rebuilt: keep the remembered selection
    private string _selectedId = "general";

    public ConfigPageViewModel(
        SettingsViewModel settings, StorageViewModel storage, AboutViewModel about, ILocalizationService localization)
    {
        Settings = settings;
        Storage = storage;
        About = about;
        _localization = localization;
        settings.Groups.CollectionChanged += (_, _) => BuildSections();
        BuildSections();
    }

    public SettingsViewModel Settings { get; }

    public StorageViewModel Storage { get; }

    public AboutViewModel About { get; }

    public ObservableCollection<ConfigSection> Sections { get; } = [];

    /// <summary>The engine groups shown on the right: the selected one, or every match while searching.</summary>
    public ObservableCollection<SettingGroupViewModel> VisibleGroups { get; } = [];

    [ObservableProperty]
    [NotifyPropertyChangedFor(nameof(ShowDesktop), nameof(ShowVocabulary), nameof(ShowStorage), nameof(ShowAbout))]
    public partial ConfigSection? SelectedSection { get; set; }

    [ObservableProperty]
    [NotifyPropertyChangedFor(nameof(IsSearching), nameof(ShowDesktop), nameof(ShowVocabulary), nameof(ShowStorage), nameof(ShowAbout))]
    public partial string SearchText { get; set; } = "";

    public bool IsSearching => !string.IsNullOrWhiteSpace(SearchText);

    /// <summary>The search matched nothing.</summary>
    [ObservableProperty]
    public partial bool HasNoResults { get; private set; }

    public bool ShowDesktop => Shows(ConfigSectionKind.Desktop);

    public bool ShowVocabulary => Shows(ConfigSectionKind.Vocabulary);

    public bool ShowStorage => Shows(ConfigSectionKind.Storage);

    public bool ShowAbout => Shows(ConfigSectionKind.About);

    /// <summary>Settings, then the option lists and the storage figures (the only service the page calls on open).</summary>
    public async Task LoadAsync(CancellationToken cancellationToken = default)
    {
        await Settings.LoadAsync(cancellationToken);
        await Settings.LoadOptionsAsync(cancellationToken);
        await Storage.LoadAsync(cancellationToken);
    }

    /// <summary>Show a section by id (<c>general</c>, <c>storage</c>…); unknown ids are ignored.</summary>
    public void Select(string id)
    {
        if (Sections.FirstOrDefault(section => section.Id == id) is { } section)
        {
            SelectedSection = section;
        }
    }

    public void RefreshTexts()
    {
        Settings.RefreshTexts();
        foreach (var section in Sections)
        {
            section.Refresh(_localization);
        }

        Storage.RefreshTexts();
        ApplyFilter();
    }

    partial void OnSelectedSectionChanged(ConfigSection? value)
    {
        if (_rebuilding || value is null)
        {
            return;
        }

        _selectedId = value.Id;
        if (IsSearching)
        {
            SearchText = ""; // picking a section leaves the search (and filters again)
            return;
        }

        ApplyFilter();
    }

    partial void OnSearchTextChanged(string value) => ApplyFilter();

    private bool Shows(ConfigSectionKind kind) => IsSearching
        ? Sections.Any(section => section.Kind == kind && section.IsVisible)
        : SelectedSection?.Kind == kind;

    private void BuildSections()
    {
        _rebuilding = true;
        Sections.Clear();
        foreach (var group in Settings.Groups)
        {
            Sections.Add(new ConfigSection(group.Id, ConfigSectionKind.Engine, group));
        }

        foreach (var (id, kind) in AppSections)
        {
            Sections.Add(new ConfigSection(id, kind));
        }

        foreach (var section in Sections)
        {
            section.Refresh(_localization);
        }

        SelectedSection = Sections.FirstOrDefault(section => section.Id == _selectedId) ?? Sections[0];
        _rebuilding = false;
        ApplyFilter();
    }

    private void ApplyFilter()
    {
        var query = SearchText.Trim();
        foreach (var group in Settings.Groups)
        {
            group.Filter(IsSearching ? query : "");
        }

        foreach (var section in Sections)
        {
            section.IsVisible = !IsSearching || (section.Group is { } group
                ? group.HasMatches
                : section.Title.Contains(query, StringComparison.CurrentCultureIgnoreCase));
        }

        VisibleGroups.Clear();
        IEnumerable<SettingGroupViewModel> groups = IsSearching
            ? Settings.Groups.Where(item => item.HasMatches)
            : SelectedSection?.Group is { } selected ? [selected] : [];
        foreach (var shown in groups)
        {
            VisibleGroups.Add(shown);
        }

        HasNoResults = IsSearching && !Sections.Any(section => section.IsVisible);
        OnPropertyChanged(nameof(ShowDesktop));
        OnPropertyChanged(nameof(ShowVocabulary));
        OnPropertyChanged(nameof(ShowStorage));
        OnPropertyChanged(nameof(ShowAbout));
    }
}
