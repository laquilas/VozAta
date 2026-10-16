using System.Globalization;
using System.Text.Json;
using CommunityToolkit.Mvvm.ComponentModel;
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
}

/// <summary>One option of a choice setting; the label is localized when a key exists.</summary>
public sealed partial class SettingChoice(string value, string? labelKey) : ObservableObject
{
    public string Value { get; } = value;

    [ObservableProperty]
    public partial string Label { get; private set; } = value;

    public void Refresh(ILocalizationService localization) =>
        Label = labelKey is null ? Value : localization[labelKey];
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
            ["en"] = "LanguageEn", ["pt"] = "LanguagePt", ["es"] = "LanguageEs", ["auto"] = "LanguageAuto",
        },
    };

    private string? _original;

    public SettingEditorViewModel(SettingSchema schema, JsonElement? value, ILocalizationService localization)
    {
        Schema = schema;
        Kind = schema switch
        {
            { Secret: true } => SettingKind.Secret,
            { Type: "number" } => SettingKind.Number,
            { Type: "integer" } => SettingKind.WholeNumber,
            { Type: "bool" } => SettingKind.Toggle,
            { Type: "choice" } => SettingKind.Choice,
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

    public IReadOnlyList<SettingChoice> Choices { get; }

    public bool IsText => Kind == SettingKind.Text;

    public bool IsSecret => Kind == SettingKind.Secret;

    public bool IsNumeric => Kind is SettingKind.Number or SettingKind.WholeNumber;

    public bool IsToggle => Kind == SettingKind.Toggle;

    public bool IsChoice => Kind == SettingKind.Choice;

    /// <summary>Decimal places for the number box (0 for integers).</summary>
    public string NumberFormat => Kind == SettingKind.WholeNumber ? "0" : "0.###";

    [ObservableProperty]
    public partial string Label { get; private set; } = "";

    [ObservableProperty]
    public partial string Help { get; private set; } = "";

    [ObservableProperty]
    [NotifyPropertyChangedFor(nameof(IsDirty))]
    public partial string TextValue { get; set; } = "";

    [ObservableProperty]
    [NotifyPropertyChangedFor(nameof(IsDirty))]
    public partial decimal? NumberValue { get; set; }

    [ObservableProperty]
    [NotifyPropertyChangedFor(nameof(IsDirty))]
    public partial bool BoolValue { get; set; }

    [ObservableProperty]
    [NotifyPropertyChangedFor(nameof(IsDirty))]
    public partial SettingChoice? SelectedChoice { get; set; }

    /// <summary>The engine's message when it rejected this value; cleared by editing.</summary>
    [ObservableProperty]
    public partial string? Error { get; set; }

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

    public void RefreshTexts(ILocalizationService localization)
    {
        Label = localization[$"Setting_{Key}"];
        Help = localization[$"SettingHelp_{Key}"];
        foreach (var choice in Choices)
        {
            choice.Refresh(localization);
        }
    }

    partial void OnTextValueChanged(string value) => Error = null;

    partial void OnNumberValueChanged(decimal? value) => Error = null;

    partial void OnBoolValueChanged(bool value) => Error = null;

    partial void OnSelectedChoiceChanged(SettingChoice? value) => Error = null;

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
