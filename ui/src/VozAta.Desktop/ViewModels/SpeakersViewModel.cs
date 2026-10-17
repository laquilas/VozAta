using System.Collections.ObjectModel;
using CommunityToolkit.Mvvm.ComponentModel;
using CommunityToolkit.Mvvm.Input;
using VozAta.Client;
using VozAta.Desktop.Services;

namespace VozAta.Desktop.ViewModels;

/// <summary>One speaker of a session: its default label, two lines it said, and the name being edited.</summary>
public sealed partial class SpeakerRow(string speakerId, string defaultLabel, string hint, string? name) : ObservableObject
{
    public string SpeakerId { get; } = speakerId;

    /// <summary>The label without a name, such as "User 1" or "Me".</summary>
    public string DefaultLabel { get; } = defaultLabel;

    /// <summary>The first two things this speaker said, to tell who is who.</summary>
    public string Hint { get; } = hint;

    [ObservableProperty]
    public partial string Name { get; set; } = name ?? "";
}

/// <summary>
/// The "Speakers" panel of a session (phase 16): rename <c>User 1</c>, <c>User 2</c>, <c>Me</c>…
/// Names are saved to the engine's <c>speakers.json</c>; the owner reloads the transcript, and when
/// minutes exist the panel offers to regenerate them with the new names.
/// </summary>
public sealed partial class SpeakersViewModel(
    IEngineClient client,
    ILocalizationService localization,
    string sessionId,
    Func<CancellationToken, Task> reloadTranscript,
    Func<bool> hasMinutes,
    Func<Task> regenerateMinutes) : ObservableObject
{
    private const int HintLines = 2;

    private const int HintLength = 80;

    public ObservableCollection<SpeakerRow> Rows { get; } = [];

    public bool HasRows => Rows.Count > 0;

    [ObservableProperty]
    [NotifyCanExecuteChangedFor(nameof(SaveCommand))]
    public partial bool IsSaving { get; private set; }

    [ObservableProperty]
    public partial string? Error { get; private set; }

    /// <summary>Feedback such as "Names saved."</summary>
    [ObservableProperty]
    public partial string? Message { get; private set; }

    /// <summary>Names were saved and minutes exist: offer "Regenerate minutes with the new names".</summary>
    [ObservableProperty]
    public partial bool OfferRegenerate { get; private set; }

    /// <summary>Build one row per speaker of <paramref name="segments"/>, in order of first appearance.</summary>
    public async Task LoadAsync(IReadOnlyList<Segment> segments, CancellationToken cancellationToken = default)
    {
        Error = null;
        Rows.Clear();
        try
        {
            if (segments.Count > 0)
            {
                var speakers = (await client.GetSpeakersAsync(sessionId, cancellationToken)).Speakers;
                foreach (var group in segments.GroupBy(segment => segment.SpeakerId))
                {
                    var info = speakers.GetValueOrDefault(group.Key);
                    Rows.Add(new SpeakerRow(group.Key, info?.DefaultLabel ?? group.First().Label, Hint(group), info?.Name));
                }
            }
        }
        catch (Exception error) when (error is EngineApiException or EngineUnavailableException)
        {
            Error = ErrorText(error);
        }
        finally
        {
            OnPropertyChanged(nameof(HasRows));
            SaveCommand.NotifyCanExecuteChanged();
        }
    }

    private bool CanSave() => !IsSaving && Rows.Count > 0;

    [RelayCommand(CanExecute = nameof(CanSave))]
    private async Task SaveAsync()
    {
        Error = Message = null;
        OfferRegenerate = false;
        IsSaving = true;
        try
        {
            var names = Rows.ToDictionary(row => row.SpeakerId, row => string.IsNullOrWhiteSpace(row.Name) ? null : row.Name.Trim());
            await client.UpdateSpeakersAsync(sessionId, names);
            await reloadTranscript(CancellationToken.None);
            OfferRegenerate = hasMinutes();
            Message = OfferRegenerate ? null : localization["SpeakersSaved"];
        }
        catch (Exception error) when (error is EngineApiException or EngineUnavailableException)
        {
            Error = ErrorText(error);
        }
        finally
        {
            IsSaving = false;
        }
    }

    [RelayCommand]
    private async Task RegenerateAsync()
    {
        OfferRegenerate = false;
        await regenerateMinutes();
    }

    [RelayCommand]
    private void DismissRegenerate() => OfferRegenerate = false;

    private static string Hint(IEnumerable<Segment> segments) =>
        string.Join(" ", segments.Take(HintLines).Select(segment => $"“{Shorten(segment.Text.Trim())}”"));

    private static string Shorten(string text) => text.Length <= HintLength ? text : text[..HintLength] + "…";

    private string ErrorText(Exception error) =>
        error is EngineUnavailableException ? localization["EngineUnavailable"] : error.Message;
}
