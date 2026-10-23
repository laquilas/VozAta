using System.ComponentModel;
using System.Text.Json;
using CommunityToolkit.Mvvm.ComponentModel;

namespace VozAta.Desktop.ViewModels;

/// <summary>
/// The Worker group's switches (phase 46): use the worker for speech, speakers and translation.
/// Each one edits its provider key (<c>STT_PROVIDER</c>, <c>DIARIZATION_PROVIDER</c>,
/// <c>TRANSLATION_PROVIDER</c>), saved with the page's Save; switching off goes back to the local
/// provider the key had (or its default).
/// </summary>
public sealed partial class WorkerTasksViewModel : ObservableObject
{
    public const string Worker = "vozata_worker";
    public const string SpeechKey = "STT_PROVIDER";
    public const string SpeakersKey = "DIARIZATION_PROVIDER";
    public const string TranslationKey = "TRANSLATION_PROVIDER";

    private readonly SettingEditorViewModel? _speech;
    private readonly SettingEditorViewModel? _speakers;
    private readonly SettingEditorViewModel? _translation;
    private readonly Dictionary<SettingEditorViewModel, string> _local = [];

    public WorkerTasksViewModel(IEnumerable<SettingEditorViewModel> editors)
    {
        var byKey = editors.ToDictionary(editor => editor.Key);
        _speech = Watch(byKey.GetValueOrDefault(SpeechKey));
        _speakers = Watch(byKey.GetValueOrDefault(SpeakersKey));
        _translation = Watch(byKey.GetValueOrDefault(TranslationKey));
    }

    public bool HasSpeech => _speech is not null;

    public bool HasSpeakers => _speakers is not null;

    public bool HasTranslation => _translation is not null;

    public bool UseForSpeech
    {
        get => Uses(_speech);
        set => Use(_speech, value);
    }

    public bool UseForSpeakers
    {
        get => Uses(_speakers);
        set => Use(_speakers, value);
    }

    public bool UseForTranslation
    {
        get => Uses(_translation);
        set => Use(_translation, value);
    }

    private SettingEditorViewModel? Watch(SettingEditorViewModel? editor)
    {
        if (editor is null)
        {
            return null;
        }

        Remember(editor);
        editor.PropertyChanged += OnEditorChanged;
        return editor;
    }

    private static bool Uses(SettingEditorViewModel? editor) => editor?.TextValue.Trim() == Worker;

    private void Use(SettingEditorViewModel? editor, bool on)
    {
        if (editor is null || Uses(editor) == on)
        {
            return;
        }

        editor.TextValue = on ? Worker : _local[editor];
    }

    /// <summary>The local provider to go back to: the current one, else the key's default.</summary>
    private void Remember(SettingEditorViewModel editor)
    {
        var value = editor.TextValue.Trim();
        if (value.Length > 0 && value != Worker)
        {
            _local[editor] = value;
        }
        else if (!_local.ContainsKey(editor))
        {
            var fallback = editor.Schema.Default.ValueKind == JsonValueKind.String ? editor.Schema.Default.GetString() : null;
            _local[editor] = fallback is { Length: > 0 } and not Worker ? fallback : "";
        }
    }

    private void OnEditorChanged(object? sender, PropertyChangedEventArgs args)
    {
        if (args.PropertyName != nameof(SettingEditorViewModel.TextValue) || sender is not SettingEditorViewModel editor)
        {
            return;
        }

        Remember(editor);
        OnPropertyChanged(
            editor == _speech ? nameof(UseForSpeech)
            : editor == _speakers ? nameof(UseForSpeakers)
            : nameof(UseForTranslation));
    }
}
