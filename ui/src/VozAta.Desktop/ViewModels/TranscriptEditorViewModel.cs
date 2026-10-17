using System.Collections.ObjectModel;
using System.ComponentModel;
using System.Globalization;
using System.Text.Json;
using CommunityToolkit.Mvvm.ComponentModel;
using CommunityToolkit.Mvvm.Input;
using VozAta.Client;
using VozAta.Desktop.Services;

namespace VozAta.Desktop.ViewModels;

/// <summary>One transcript segment in Edit mode: its text in a TextBox, compared with what was loaded.</summary>
public sealed partial class EditableSegment : ObservableObject
{
    public EditableSegment(Segment segment)
    {
        SegmentId = segment.SegmentId;
        Header = $"[{TranscriptLine.FormatTime(segment.Start)}] {segment.Label}";
        Color = TranscriptLine.ColorOf(segment.Channel);
        OriginalText = segment.Text;
        Text = segment.Text;
    }

    public string SegmentId { get; }

    /// <summary><c>[hh:mm:ss] Label</c> above the text box.</summary>
    public string Header { get; }

    public string Color { get; }

    public string OriginalText { get; }

    [ObservableProperty]
    [NotifyPropertyChangedFor(nameof(IsDirty))]
    public partial string Text { get; set; }

    /// <summary>The text differs from the loaded one (surrounding spaces do not count).</summary>
    public bool IsDirty => Text.Trim() != OriginalText.Trim();

    public void Reset() => Text = OriginalText;

    /// <summary>What screen readers announce for the text box.</summary>
    public override string ToString() => Header;
}

/// <summary>
/// Edit mode of a session's transcript (phase 21): correct segment texts, save only the real
/// changes, revert to the original transcript, and guard unsaved changes on navigation.
/// </summary>
public sealed partial class TranscriptEditorViewModel(
    IEngineClient client,
    ILocalizationService localization,
    IDialogService? dialogs,
    string sessionId) : ObservableObject
{
    public ObservableCollection<EditableSegment> Segments { get; } = [];

    /// <summary>Words below this probability are highlighted (<c>LOW_CONFIDENCE_THRESHOLD</c>).</summary>
    [ObservableProperty]
    public partial double Threshold { get; private set; } = LowConfidence.DefaultThreshold;

    [ObservableProperty]
    [NotifyCanExecuteChangedFor(nameof(EditCommand), nameof(CancelEditCommand), nameof(SaveCommand), nameof(RevertCommand))]
    public partial bool IsEditing { get; private set; }

    [ObservableProperty]
    [NotifyCanExecuteChangedFor(nameof(EditCommand), nameof(CancelEditCommand), nameof(SaveCommand), nameof(RevertCommand))]
    public partial bool IsSaving { get; private set; }

    /// <summary>Some segment text differs from the loaded transcript.</summary>
    [ObservableProperty]
    [NotifyCanExecuteChangedFor(nameof(SaveCommand))]
    public partial bool IsDirty { get; private set; }

    /// <summary>The loaded transcript is the user's edited copy (Revert is offered).</summary>
    [ObservableProperty]
    [NotifyCanExecuteChangedFor(nameof(RevertCommand))]
    public partial bool HasEdits { get; private set; }

    /// <summary>After a save or revert: suggest regenerating the minutes so they use the transcript.</summary>
    [ObservableProperty]
    public partial bool SuggestRegenerate { get; set; }

    [ObservableProperty]
    public partial string? Error { get; private set; }

    /// <summary>The session is still being recorded: no editing.</summary>
    [ObservableProperty]
    [NotifyCanExecuteChangedFor(nameof(EditCommand))]
    public partial bool IsLive { get; set; }

    /// <summary>Reloads the transcript after a save or revert (set by the session detail).</summary>
    public Func<Task>? Reload { get; init; }

    /// <summary>Read <c>LOW_CONFIDENCE_THRESHOLD</c>; keeps the default when the engine cannot tell.</summary>
    public async Task LoadThresholdAsync(CancellationToken cancellationToken = default)
    {
        try
        {
            var settings = await client.GetSettingsAsync(cancellationToken);
            if (double.TryParse(settings.GetString("LOW_CONFIDENCE_THRESHOLD"), NumberStyles.Float, CultureInfo.InvariantCulture, out var value))
            {
                Threshold = value;
            }
        }
        catch (Exception error) when (error is EngineApiException or EngineUnavailableException or JsonException)
        {
            // Highlighting is a hint: keep the default threshold.
        }
    }

    /// <summary>Show <paramref name="transcript"/>: leaves Edit mode and forgets unsaved changes.</summary>
    public void Load(Transcript transcript)
    {
        foreach (var segment in Segments)
        {
            segment.PropertyChanged -= OnSegmentChanged;
        }

        Segments.Clear();
        foreach (var segment in transcript.Segments)
        {
            var editable = new EditableSegment(segment);
            editable.PropertyChanged += OnSegmentChanged;
            Segments.Add(editable);
        }

        HasEdits = transcript.Source == "edited";
        IsEditing = false;
        IsDirty = false;
        EditCommand.NotifyCanExecuteChanged();
    }

    /// <summary>Read-mode parts of <paramref name="segment"/>; null when nothing is highlighted.</summary>
    public IReadOnlyList<TextPart>? Highlight(Segment segment) =>
        segment.Edited ? null : LowConfidence.Split(segment.Text, segment.Words, Threshold);

    /// <summary>The save payload: only segments whose text really changed, trimmed.</summary>
    public IReadOnlyList<SegmentTextEdit> Changes() =>
        [.. Segments.Where(segment => segment.IsDirty).Select(segment => new SegmentTextEdit(segment.SegmentId, segment.Text.Trim()))];

    /// <summary>Whether the user may leave; asks before dropping unsaved changes (and drops them on yes).</summary>
    public async Task<bool> ConfirmLeaveAsync()
    {
        if (!IsDirty)
        {
            return true;
        }

        var discard = dialogs is null || await dialogs.ConfirmAsync(
            localization["ConfirmDiscardEditsTitle"],
            localization["ConfirmDiscardEditsMessage"],
            localization["ConfirmDiscardEditsYes"],
            localization["ConfirmDiscardEditsNo"]);
        if (discard)
        {
            Discard();
        }

        return discard;
    }

    /// <summary>Drop unsaved changes and go back to read mode.</summary>
    public void Discard()
    {
        foreach (var segment in Segments)
        {
            segment.Reset();
        }

        IsEditing = false;
        Error = null;
    }

    private bool CanEdit() => !IsEditing && !IsSaving && !IsLive && Segments.Count > 0;

    [RelayCommand(CanExecute = nameof(CanEdit))]
    private void Edit()
    {
        Error = null;
        SuggestRegenerate = false;
        IsEditing = true;
    }

    private bool CanCancelEdit() => IsEditing && !IsSaving;

    [RelayCommand(CanExecute = nameof(CanCancelEdit))]
    private void CancelEdit() => Discard();

    private bool CanSave() => IsEditing && IsDirty && !IsSaving;

    [RelayCommand(CanExecute = nameof(CanSave))]
    private async Task SaveAsync()
    {
        var changes = Changes();
        if (changes.Any(change => change.Text.Length == 0))
        {
            Error = localization["TranscriptEmptySegment"];
            return;
        }

        await RunAsync(async () =>
        {
            await client.UpdateTranscriptAsync(sessionId, changes);
            IsEditing = false;
        });
    }

    private bool CanRevert() => HasEdits && !IsSaving && !IsEditing;

    [RelayCommand(CanExecute = nameof(CanRevert))]
    private async Task RevertAsync()
    {
        var confirmed = dialogs is null || await dialogs.ConfirmAsync(
            localization["ConfirmRevertTitle"],
            localization["ConfirmRevertMessage"],
            localization["ConfirmRevertYes"],
            localization["ConfirmRevertNo"]);
        if (confirmed)
        {
            await RunAsync(() => client.RevertTranscriptAsync(sessionId));
        }
    }

    /// <summary>Save or revert, then reload the transcript and suggest regenerating the minutes.</summary>
    private async Task RunAsync(Func<Task> change)
    {
        Error = null;
        IsSaving = true;
        try
        {
            await change();
            SuggestRegenerate = true;
            if (Reload is not null)
            {
                await Reload();
            }
        }
        catch (Exception error) when (error is EngineApiException or EngineUnavailableException)
        {
            Error = error is EngineUnavailableException ? localization["EngineUnavailable"] : error.Message;
        }
        finally
        {
            IsSaving = false;
        }
    }

    private void OnSegmentChanged(object? sender, PropertyChangedEventArgs args)
    {
        if (args.PropertyName == nameof(EditableSegment.IsDirty))
        {
            IsDirty = Segments.Any(segment => segment.IsDirty);
        }
    }
}
