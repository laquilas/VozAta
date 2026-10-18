namespace VozAta.Desktop.ViewModels;

// The Meetings page (phase 36) is MeetingsPageViewModel.cs.

/// <summary>
/// The Ask page (phase 35): questions about one meeting or all of them. A source opens its meeting
/// on the Meetings page.
/// </summary>
public sealed class AskPageViewModel
{
    public AskPageViewModel(AskViewModel ask, Action showMeetings)
    {
        Ask = ask;
        var open = ask.OpenCitation;
        ask.OpenCitation = citation =>
        {
            showMeetings();
            return open is null ? Task.CompletedTask : open(citation);
        };
    }

    public AskViewModel Ask { get; }
}
