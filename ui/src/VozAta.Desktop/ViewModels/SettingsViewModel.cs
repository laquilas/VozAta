using System.Collections.ObjectModel;
using System.ComponentModel;
using System.Text.Json;
using CommunityToolkit.Mvvm.ComponentModel;
using CommunityToolkit.Mvvm.Input;
using VozAta.Client;
using VozAta.Desktop.Services;

namespace VozAta.Desktop.ViewModels;

/// <summary>A titled section of the settings page.</summary>
public sealed partial class SettingGroupViewModel(string id, IReadOnlyList<SettingEditorViewModel> editors) : ObservableObject
{
    public string Id { get; } = id;

    public IReadOnlyList<SettingEditorViewModel> Editors { get; } = editors;

    [ObservableProperty]
    public partial string Title { get; private set; } = id;

    public void RefreshTexts(ILocalizationService localization)
    {
        Title = localization[$"SettingsGroup_{Id}"];
        foreach (var editor in Editors)
        {
            editor.RefreshTexts(localization);
        }
    }
}

/// <summary>
/// The engine settings page, generated from the <c>GET /settings</c> schema. Save sends only the
/// changed keys; keys read at engine start-up end in a restart prompt.
/// </summary>
public sealed partial class SettingsViewModel(IEngineClient client, IEngineProcess process, ILocalizationService localization)
    : ObservableObject
{
    private static readonly string[] GroupOrder = ["general", "audio", "segmentation", "transcription", "speakers", "minutes", "tasks", "api"];

    public ObservableCollection<SettingGroupViewModel> Groups { get; } = [];

    /// <summary>Labels of saved keys that only apply after an engine restart.</summary>
    public ObservableCollection<string> RestartKeys { get; } = [];

    [ObservableProperty]
    [NotifyCanExecuteChangedFor(nameof(SaveCommand), nameof(DiscardCommand))]
    public partial bool IsDirty { get; private set; }

    [ObservableProperty]
    [NotifyCanExecuteChangedFor(nameof(SaveCommand), nameof(RestartEngineCommand))]
    public partial bool IsBusy { get; private set; }

    [ObservableProperty]
    public partial string? Message { get; private set; }

    [ObservableProperty]
    public partial string? Error { get; private set; }

    /// <summary>Raised with the saved values as text (null = cleared) after a successful save.</summary>
    public event Action<IReadOnlyDictionary<string, string?>>? Saved;

    private IEnumerable<SettingEditorViewModel> Editors => Groups.SelectMany(group => group.Editors);

    public async Task LoadAsync(CancellationToken cancellationToken = default)
    {
        Error = null;
        try
        {
            var settings = await client.GetSettingsAsync(cancellationToken);
            Groups.Clear();
            foreach (var group in settings.Schema.GroupBy(item => item.Group).OrderBy(group => Order(group.Key)))
            {
                var editors = group
                    .Select(item => new SettingEditorViewModel(item, Value(settings.Values, item.Key), localization))
                    .ToList();
                foreach (var editor in editors)
                {
                    editor.PropertyChanged += OnEditorChanged;
                }

                var section = new SettingGroupViewModel(group.Key, editors);
                section.RefreshTexts(localization);
                Groups.Add(section);
            }

            UpdateDirty();
        }
        catch (Exception error) when (error is EngineApiException or EngineUnavailableException)
        {
            Error = ErrorText(error);
        }
    }

    /// <summary>Save one value chosen elsewhere (the interface language selector).</summary>
    public async Task SaveValueAsync(string key, object? value)
    {
        var result = await client.UpdateSettingsAsync(new Dictionary<string, object?> { [key] = value });
        Editors.FirstOrDefault(editor => editor.Key == key)?.Accept(Value(result.Values, key));
        UpdateDirty();
    }

    public void RefreshTexts()
    {
        foreach (var group in Groups)
        {
            group.RefreshTexts(localization);
        }
    }

    private bool CanSave() => IsDirty && !IsBusy;

    [RelayCommand(CanExecute = nameof(CanSave))]
    private async Task SaveAsync()
    {
        var dirty = Editors.Where(editor => editor.IsDirty).ToList();
        IsBusy = true;
        Message = Error = null;
        try
        {
            var result = await client.UpdateSettingsAsync(dirty.ToDictionary(editor => editor.Key, editor => editor.ToJson()));
            var saved = new Dictionary<string, string?>();
            foreach (var editor in dirty)
            {
                editor.Accept(Value(result.Values, editor.Key));
                saved[editor.Key] = editor.ToJson() switch
                {
                    null => null,
                    bool flag => flag ? "true" : "false",
                    var other => Convert.ToString(other, System.Globalization.CultureInfo.InvariantCulture),
                };
            }

            foreach (var key in result.RestartRequired)
            {
                var label = localization[$"Setting_{key}"];
                if (!RestartKeys.Contains(label))
                {
                    RestartKeys.Add(label);
                }
            }

            Message = localization["SettingsSaved"];
            Saved?.Invoke(saved);
        }
        catch (EngineApiException error) when (error.Key is not null && Editors.Any(editor => editor.Key == error.Key))
        {
            Editors.First(editor => editor.Key == error.Key).Error = error.Message;
        }
        catch (Exception error) when (error is EngineApiException or EngineUnavailableException)
        {
            Error = ErrorText(error);
        }
        finally
        {
            IsBusy = false;
            UpdateDirty();
        }
    }

    [RelayCommand(CanExecute = nameof(IsDirty))]
    private void Discard()
    {
        foreach (var editor in Editors)
        {
            editor.Reset();
        }

        Message = Error = null;
        UpdateDirty();
    }

    private bool CanRestart() => RestartKeys.Count > 0 && !IsBusy;

    [RelayCommand(CanExecute = nameof(CanRestart))]
    private async Task RestartEngineAsync()
    {
        IsBusy = true;
        Message = Error = null;
        try
        {
            switch (await process.RestartAsync())
            {
                case EngineRestartResult.Restarted:
                    RestartKeys.Clear();
                    Message = localization["EngineRestarted"];
                    break;
                case EngineRestartResult.NotOwned:
                    Message = localization["EngineRestartManual"];
                    break;
                default:
                    Error = localization["EngineRestartFailed"];
                    break;
            }
        }
        finally
        {
            IsBusy = false;
            RestartEngineCommand.NotifyCanExecuteChanged();
        }
    }

    private void OnEditorChanged(object? sender, PropertyChangedEventArgs args)
    {
        if (args.PropertyName == nameof(SettingEditorViewModel.IsDirty))
        {
            UpdateDirty();
        }
    }

    private void UpdateDirty()
    {
        IsDirty = Editors.Any(editor => editor.IsDirty);
        RestartEngineCommand.NotifyCanExecuteChanged();
    }

    private static int Order(string group)
    {
        var index = Array.IndexOf(GroupOrder, group);
        return index < 0 ? GroupOrder.Length : index;
    }

    private static JsonElement? Value(IReadOnlyDictionary<string, JsonElement> values, string key) =>
        values.TryGetValue(key, out var value) ? value : null;

    private string ErrorText(Exception error) =>
        error is EngineUnavailableException ? localization["EngineUnavailable"] : error.Message;
}
