namespace VozAta.Desktop.ViewModels;

/// <summary>The Meetings page (phase 35): today the history list and detail, until phase 36 redesigns it.</summary>
public sealed class MeetingsPageViewModel(HistoryViewModel history)
{
    public HistoryViewModel History { get; } = history;
}

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

/// <summary>The Config page (phase 35): today the settings page, until phase 38 redesigns it.</summary>
public sealed class ConfigPageViewModel(SettingsViewModel settings)
{
    public SettingsViewModel Settings { get; } = settings;
}
