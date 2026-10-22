using System.Collections.ObjectModel;
using System.Globalization;
using System.Text.Json;
using CommunityToolkit.Mvvm.ComponentModel;
using CommunityToolkit.Mvvm.Input;
using VozAta.Client;
using VozAta.Desktop.Services;

namespace VozAta.Desktop.ViewModels;

/// <summary>Which editor the settings page shows for a key.</summary>
public enum SettingKind
{
    Text,
    Number,
    WholeNumber,
    Toggle,
    Choice,
    Secret,

    /// <summary>Free text with a list from <c>GET /settings/options</c> (an editable combo box, phase 38).</summary>
    Options,

    /// <summary>A file or folder path with a Browse button (phase 38).</summary>
    Path,

    /// <summary>An http(s) address, validated while typing (phase 38).</summary>
    Url,
}

/// <summary>One option of a choice setting; the label is localized when a key exists.</summary>
public sealed partial class SettingChoice(string value, string? labelKey, string? label = null) : ObservableObject
{
    public string Value { get; } = value;

    [ObservableProperty]
    public partial string Label { get; private set; } = label ?? value;

    /// <summary>False for a model that is not downloaded or a device this PC lacks.</summary>
    [ObservableProperty]
    public partial bool IsAvailable { get; set; } = true;

    public void Refresh(ILocalizationService localization)
    {
        if (labelKey is not null)
        {
            Label = localization[labelKey];
        }
    }

    /// <summary>What screen readers announce for the option (and what an editable combo box types).</summary>
    public override string ToString() => labelKey is null ? Value : Label;
}

/// <summary>
/// One setting, edited with the control its schema type asks for. It remembers the loaded value
/// for dirty tracking and turns the edited value into the JSON value <c>PUT /settings</c> expects.
/// </summary>
public sealed partial class SettingEditorViewModel : ObservableObject
{
    private static readonly Dictionary<string, Dictionary<string, string>> ChoiceLabels = new()
    {
        ["APP_LANGUAGE"] = new() { ["en"] = "AppLanguageEn", ["pt-BR"] = "AppLanguagePtBr", ["es"] = "AppLanguageEs" },
        ["TRANSCRIPTION_LANGUAGE"] = new()
        {
            ["en"] = "LanguageEn",
            ["pt"] = "LanguagePt",
            ["es"] = "LanguageEs",
            ["auto"] = "LanguageAuto",
        },
        ["TRANSLATE_TO"] = new()
        {
            ["off"] = "TranslateOff",
            ["en"] = "LanguageEn",
            ["pt"] = "LanguagePt",
            ["es"] = "LanguageEs",
        },
        ["MINUTES_TEMPLATE"] = new()
        {
            ["general"] = "TemplateName_general",
            ["daily"] = "TemplateName_daily",
            ["one_on_one"] = "TemplateName_one_on_one",
            ["client"] = "TemplateName_client",
            ["retrospective"] = "TemplateName_retrospective",
        },
    };

    private readonly ILocalizationService _localization;
    private readonly IPathPicker? _paths;
    private string? _original;
    private bool _optionsKnown; // a list was loaded and its service answered

    public SettingEditorViewModel(
        SettingSchema schema, JsonElement? value, ILocalizationService localization, IPathPicker? paths = null)
    {
        Schema = schema;
        _localization = localization;
        _paths = paths;
        Kind = schema switch
        {
            { Secret: true } => SettingKind.Secret,
            { Type: "number" } => SettingKind.Number,
            { Type: "integer" } => SettingKind.WholeNumber,
            { Type: "bool" } => SettingKind.Toggle,
            { Type: "choice" } => SettingKind.Choice,
            { OptionsSource: not null } => SettingKind.Options,
            { Type: "path" } => SettingKind.Path,
            { Type: "url" } => SettingKind.Url,
            _ => SettingKind.Text,
        };
        var labels = ChoiceLabels.GetValueOrDefault(schema.Key);
        Choices = [.. (schema.Choices ?? []).Select(choice => new SettingChoice(choice, labels?.GetValueOrDefault(choice)))];
        Load(Text(value));
        RefreshTexts(localization);
    }

    public SettingSchema Schema { get; }

    public string Key => Schema.Key;

    public SettingKind Kind { get; }

    public bool NeedsRestart => Schema.NeedsRestart;

    /// <summary>The <c>GET /settings/options</c> list this key uses (null: none).</summary>
    public string? OptionsSource => Schema.OptionsSource;

    public IReadOnlyList<SettingChoice> Choices { get; }

    /// <summary>The list of an <see cref="SettingKind.Options"/> editor (filled by <see cref="SetOptions"/>).</summary>
    public ObservableCollection<SettingChoice> Options { get; } = [];

    /// <summary>The service check next to this key (Ollama, speech API, tokens), if any.</summary>
    public ConnectionTestViewModel? Test { get; set; }

    public bool HasTest => Test is not null;

    public bool IsText => Kind is SettingKind.Text or SettingKind.Url;

    public bool IsSecret => Kind == SettingKind.Secret;

    public bool IsNumeric => Kind is SettingKind.Number or SettingKind.WholeNumber;

    public bool IsToggle => Kind == SettingKind.Toggle;

    public bool IsChoice => Kind == SettingKind.Choice;

    public bool IsOptions => Kind == SettingKind.Options;

    public bool IsPath => Kind == SettingKind.Path;

    /// <summary>Decimal places for the number box (0 for integers).</summary>
    public string NumberFormat => Kind == SettingKind.WholeNumber ? "0" : "0.###";

    [ObservableProperty]
    public partial string Label { get; private set; } = "";

    [ObservableProperty]
    public partial string Help { get; private set; } = "";

    [ObservableProperty]
    [NotifyPropertyChangedFor(nameof(IsDirty), nameof(IsNotInstalled))]
    public partial string TextValue { get; set; } = "";

    [ObservableProperty]
    [NotifyPropertyChangedFor(nameof(IsDirty))]
    public partial decimal? NumberValue { get; set; }

    [ObservableProperty]
    [NotifyPropertyChangedFor(nameof(IsDirty))]
    public partial bool BoolValue { get; set; }

    [ObservableProperty]
    [NotifyPropertyChangedFor(nameof(IsDirty), nameof(IsNotInstalled))]
    public partial SettingChoice? SelectedChoice { get; set; }

    /// <summary>The engine's message when it rejected this value; cleared by editing.</summary>
    [ObservableProperty]
    public partial string? Error { get; set; }

    /// <summary>A problem found while typing (an address that is not http/https); blocks Save.</summary>
    [ObservableProperty]
    [NotifyPropertyChangedFor(nameof(HasValidationError))]
    public partial string? ValidationError { get; private set; }

    public bool HasValidationError => ValidationError is not null;

    /// <summary>
    /// A line under the field: the Ollama URL names the other PC that receives the transcripts
    /// (phase 43); null for every other field and for a server on this PC.
    /// </summary>
    [ObservableProperty]
    public partial string? Note { get; private set; }

    /// <summary>The list was read but its service did not answer (Ollama stopped).</summary>
    [ObservableProperty]
    public partial bool OptionsUnreachable { get; private set; }

    /// <summary>A secret is being replaced: the password box is shown, empty.</summary>
    [ObservableProperty]
    [NotifyPropertyChangedFor(nameof(IsDirty), nameof(IsEditingSecret), nameof(SecretStatus))]
    public partial bool IsReplacingSecret { get; private set; }

    /// <summary>A stored secret will be removed on Save.</summary>
    [ObservableProperty]
    [NotifyPropertyChangedFor(nameof(IsDirty), nameof(IsEditingSecret), nameof(SecretStatus))]
    public partial bool IsRemovingSecret { get; private set; }

    /// <summary>Shown by the search filter.</summary>
    [ObservableProperty]
    public partial bool IsVisible { get; set; } = true;

    /// <summary>The engine has a value for this secret (it never sends the value itself).</summary>
    public bool HasStoredSecret => IsSecret && _original is not null;

    /// <summary>The password box is shown: nothing stored yet, or Replace was chosen.</summary>
    public bool IsEditingSecret => IsSecret && !IsRemovingSecret && (IsReplacingSecret || !HasStoredSecret);

    /// <summary>"Saved (hidden)", "Not set" or "Removed when you save".</summary>
    public string SecretStatus => _localization[
        IsRemovingSecret ? "SecretWillBeRemoved" : HasStoredSecret ? "SecretStored" : "SecretNotSet"];

    /// <summary>The value is not in the loaded list, or the list marks it unavailable ("not installed").</summary>
    public bool IsNotInstalled => Kind switch
    {
        SettingKind.Options => _optionsKnown && !string.IsNullOrWhiteSpace(TextValue)
            && !Options.Any(option => option.Value == TextValue.Trim() && option.IsAvailable),
        SettingKind.Choice => SelectedChoice is { IsAvailable: false },
        _ => false,
    };

    public bool IsDirty => Current() != _original;

    /// <summary>The edited value for <c>PUT /settings</c> (null clears the key).</summary>
    public object? ToJson()
    {
        var text = Current();
        return Kind switch
        {
            _ when text is null => null,
            SettingKind.Number => (double)NumberValue!.Value,
            SettingKind.WholeNumber => (int)NumberValue!.Value,
            SettingKind.Toggle => BoolValue,
            _ => text,
        };
    }

    /// <summary>Take <paramref name="value"/> as the saved value (after loading or saving).</summary>
    public void Accept(JsonElement? value) => Load(Text(value));

    /// <summary>Back to the saved value.</summary>
    public void Reset() => Load(_original);

    /// <summary>
    /// Fill the list from <c>GET /settings/options</c>: an <see cref="SettingKind.Options"/> editor
    /// offers it (a typed value outside it is kept); a choice marks the unavailable entries.
    /// </summary>
    public void SetOptions(IReadOnlyList<SettingOption> items, bool reachable)
    {
        OptionsUnreachable = !reachable;
        _optionsKnown = reachable;
        if (Kind == SettingKind.Choice)
        {
            foreach (var choice in Choices)
            {
                choice.IsAvailable = items.FirstOrDefault(item => item.Value == choice.Value)?.Available ?? true;
            }
        }
        else
        {
            Options.Clear();
            foreach (var item in items)
            {
                Options.Add(new SettingChoice(item.Value, null, item.Label) { IsAvailable = item.Available });
            }
        }

        OnPropertyChanged(nameof(IsNotInstalled));
    }

    /// <summary>Whether the label, key or help text contains <paramref name="query"/> (search box).</summary>
    public bool Matches(string query) =>
        string.IsNullOrWhiteSpace(query)
        || Label.Contains(query.Trim(), StringComparison.CurrentCultureIgnoreCase)
        || Key.Contains(query.Trim(), StringComparison.OrdinalIgnoreCase)
        || Help.Contains(query.Trim(), StringComparison.CurrentCultureIgnoreCase);

    public void RefreshTexts(ILocalizationService localization)
    {
        Label = localization[$"Setting_{Key}"];
        Help = localization[$"SettingHelp_{Key}"];
        foreach (var choice in Choices)
        {
            choice.Refresh(localization);
        }

        Validate();
        UpdateNote();
        OnPropertyChanged(nameof(SecretStatus));
        Test?.RefreshTexts();
    }

    [RelayCommand]
    private void ReplaceSecret()
    {
        IsRemovingSecret = false;
        TextValue = "";
        IsReplacingSecret = true;
    }

    [RelayCommand]
    private void RemoveSecret()
    {
        IsReplacingSecret = false;
        TextValue = "";
        IsRemovingSecret = true;
    }

    /// <summary>Keep the stored secret (undo Replace / Remove).</summary>
    [RelayCommand]
    private void KeepSecret() => Reset();

    private bool CanBrowse() => _paths is not null;

    /// <summary>Pick a folder (a file for <c>*_FILE</c> keys) and put its path in the box.</summary>
    [RelayCommand(CanExecute = nameof(CanBrowse))]
    private async Task BrowseAsync()
    {
        var current = string.IsNullOrWhiteSpace(TextValue) ? null : TextValue.Trim();
        string? picked;
        if (Key.EndsWith("_FILE", StringComparison.Ordinal))
        {
            picked = await _paths!.PickFileAsync(Label, current);
        }
        else if (Key.EndsWith("_DIR", StringComparison.Ordinal))
        {
            picked = await _paths!.PickFolderAsync(Label, current);
        }
        else
        {
            // A file the engine creates (DATABASE_PATH): choose the folder, keep the file name.
            var folder = await _paths!.PickFolderAsync(Label, current is null ? null : System.IO.Path.GetDirectoryName(current));
            picked = folder is null ? null : System.IO.Path.Combine(folder, FileName(current));
        }

        if (picked is not null)
        {
            TextValue = picked;
        }
    }

    partial void OnTextValueChanged(string value)
    {
        Error = null;
        Validate();
        UpdateNote();
    }

    private void UpdateNote() =>
        Note = Key == "OLLAMA_URL" && !NetworkAddress.IsLocalUrl(TextValue)
            ? _localization.Format("RemoteOllamaNote", NetworkAddress.Host(TextValue))
            : null;

    partial void OnNumberValueChanged(decimal? value) => Error = null;

    partial void OnBoolValueChanged(bool value) => Error = null;

    partial void OnSelectedChoiceChanged(SettingChoice? value) => Error = null;

    private void Validate()
    {
        var text = TextValue.Trim();
        ValidationError = Kind == SettingKind.Url && text.Length > 0
            && !(Uri.TryCreate(text, UriKind.Absolute, out var uri) && (uri.Scheme == Uri.UriSchemeHttp || uri.Scheme == Uri.UriSchemeHttps))
            ? _localization["SettingInvalidUrl"]
            : null;
    }

    private string FileName(string? current) =>
        current is not null && System.IO.Path.GetFileName(current) is { Length: > 0 } name ? name
        : Schema.Default.ValueKind == JsonValueKind.String && System.IO.Path.GetFileName(Schema.Default.GetString()) is { Length: > 0 } fallback ? fallback
        : "vozata.db";

    private void Load(string? text)
    {
        _original = text;
        switch (Kind)
        {
            case SettingKind.Number or SettingKind.WholeNumber:
                NumberValue = text is null ? null : decimal.Parse(text, CultureInfo.InvariantCulture);
                break;
            case SettingKind.Toggle:
                BoolValue = text == "true";
                break;
            case SettingKind.Choice:
                SelectedChoice = Choices.FirstOrDefault(choice => choice.Value == text);
                break;
            case SettingKind.Secret:
                IsReplacingSecret = IsRemovingSecret = false;
                TextValue = ""; // the stored value never reaches the page (only the mask does)
                OnPropertyChanged(nameof(HasStoredSecret));
                OnPropertyChanged(nameof(IsEditingSecret));
                OnPropertyChanged(nameof(SecretStatus));
                break;
            default:
                TextValue = text ?? "";
                break;
        }

        Error = null;
        OnPropertyChanged(nameof(IsDirty));
    }

    /// <summary>The edited value as canonical text (null = not set), comparable with the loaded one.</summary>
    private string? Current() => Kind switch
    {
        SettingKind.Number or SettingKind.WholeNumber => NumberValue?.ToString(Kind == SettingKind.WholeNumber ? "0" : "0.############", CultureInfo.InvariantCulture),
        SettingKind.Toggle => BoolValue ? "true" : "false",
        SettingKind.Choice => SelectedChoice?.Value,
        SettingKind.Secret when IsRemovingSecret => null,
        SettingKind.Secret => string.IsNullOrWhiteSpace(TextValue) ? _original : TextValue, // blank: keep
        _ => string.IsNullOrWhiteSpace(TextValue) ? null : TextValue,
    };

    private string? Text(JsonElement? value)
    {
        if (value is not { } element)
        {
            return null;
        }

        return element.ValueKind switch
        {
            JsonValueKind.True => "true",
            JsonValueKind.False => "false",
            JsonValueKind.Number => element.GetDecimal().ToString(
                Kind == SettingKind.WholeNumber ? "0" : "0.############", CultureInfo.InvariantCulture),
            JsonValueKind.String => string.IsNullOrEmpty(element.GetString()) ? null : element.GetString(),
            JsonValueKind.Null or JsonValueKind.Undefined => null,
            _ => element.GetRawText(),
        };
    }
}
