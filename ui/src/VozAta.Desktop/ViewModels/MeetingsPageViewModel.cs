using System.Collections.ObjectModel;
using System.ComponentModel;
using System.Globalization;
using CommunityToolkit.Mvvm.ComponentModel;
using CommunityToolkit.Mvvm.Input;
using VozAta.Client;
using VozAta.Desktop.Services;

namespace VozAta.Desktop.ViewModels;

/// <summary>
/// The Meetings page (phase 36), laid out like Toggl Track's time entries: a week at a time
/// (Monday first) with the week total on top, day groups with their totals, the live meeting pinned
/// on top, and older weeks loaded while scrolling down. A meeting opens in the detail of
/// <see cref="History"/> on the right (until phase 37); search reuses its <see cref="SearchViewModel"/>.
/// Rename, delete, play and export are in <c>MeetingsPageViewModel.Actions.cs</c>.
/// </summary>
public sealed partial class MeetingsPageViewModel : ObservableObject, IDisposable
{
    /// <summary>Scrolling back skips at most this many empty weeks per load.</summary>
    public const int MaxEmptyWeeks = 26;

    private static readonly Dictionary<string, string> LanguageKeys = new()
    {
        ["en"] = "LanguageEn",
        ["pt"] = "LanguagePt",
        ["es"] = "LanguageEs",
    };

    private static readonly (string Format, string LabelKey)[] ExportFormats =
        [("md", "ExportMarkdown"), ("docx", "ExportWord"), ("pdf", "ExportPdf")];

    private readonly IEngineClient _client;
    private readonly ILocalizationService _localization;
    private readonly IClock _clock;
    private readonly IDialogService _dialogs;
    private readonly IShellService _shell;
    private readonly IFileSaver _saver;
    private readonly MinutesTemplatesViewModel? _templates;
    private readonly Func<TimeSpan, CancellationToken, Task> _delay;
    private readonly List<SessionDay> _days = []; // every loaded day, newest first
    private DateOnly _oldest; // the first loaded day (a Monday)
    private string _storage = "files";

    /// <param name="delay">Waits out the undo window of a delete (tests pass a controllable one).</param>
    public MeetingsPageViewModel(
        IEngineClient client,
        HistoryViewModel history,
        ILocalizationService localization,
        IClock clock,
        IDialogService dialogs,
        IShellService shell,
        IFileSaver saver,
        MinutesTemplatesViewModel? templates = null,
        Func<TimeSpan, CancellationToken, Task>? delay = null)
    {
        _client = client;
        History = history;
        _localization = localization;
        _clock = clock;
        _dialogs = dialogs;
        _shell = shell;
        _saver = saver;
        _templates = templates;
        _delay = delay ?? Task.Delay;
        WeekStart = StartOfWeek(Today);
        _oldest = WeekStart;
        WeekTotal = FormatDuration(0);
        history.PropertyChanged += OnHistoryChanged;
        history.Search.Groups.CollectionChanged += (_, _) => RebuildMatches();
    }

    /// <summary>The detail on the right, the paged list the Ask page opens citations in, and search.</summary>
    public HistoryViewModel History { get; }

    /// <summary>Search across every transcript (phase 22): matching meetings replace the weeks.</summary>
    public SearchViewModel Search => History.Search;

    /// <summary>The loaded weeks, newest first; the first one is <see cref="WeekStart"/>.</summary>
    public ObservableCollection<MeetingWeek> Weeks { get; } = [];

    /// <summary>The meeting being recorded, pinned on top with a pulsing dot.</summary>
    [ObservableProperty]
    [NotifyPropertyChangedFor(nameof(IsEmpty))]
    public partial MeetingRow? Live { get; private set; }

    /// <summary>The Monday of the week in the header.</summary>
    [ObservableProperty]
    [NotifyPropertyChangedFor(nameof(WeekLabel), nameof(IsThisWeek))]
    [NotifyCanExecuteChangedFor(nameof(NextWeekCommand), nameof(ThisWeekCommand))]
    public partial DateOnly WeekStart { get; private set; }

    /// <summary>The header total of <see cref="WeekStart"/>'s week (<c>h:mm:ss</c>).</summary>
    [ObservableProperty]
    public partial string WeekTotal { get; private set; }

    /// <summary>Meetings started before the oldest loaded week exist.</summary>
    [ObservableProperty]
    [NotifyCanExecuteChangedFor(nameof(LoadOlderCommand))]
    public partial bool HasEarlier { get; private set; }

    [ObservableProperty]
    [NotifyPropertyChangedFor(nameof(IsEmpty))]
    [NotifyCanExecuteChangedFor(nameof(LoadOlderCommand))]
    public partial bool IsLoading { get; private set; }

    [ObservableProperty]
    [NotifyCanExecuteChangedFor(nameof(LoadOlderCommand))]
    public partial bool IsLoadingOlder { get; private set; }

    [ObservableProperty]
    [NotifyPropertyChangedFor(nameof(IsEmpty))]
    public partial string? Error { get; private set; }

    /// <summary>"This week", "Last week" or "6 – 12 Oct".</summary>
    public string WeekLabel => WeekLabelFor(WeekStart);

    public bool IsThisWeek => WeekStart == StartOfWeek(Today);

    /// <summary>No meeting in the loaded weeks (not while loading or after an error).</summary>
    public bool IsEmpty => Weeks.Count == 0 && Live is null && !IsLoading && Error is null;

    /// <summary>The load started by the last navigation (tests await it).</summary>
    public Task Loading { get; private set; } = Task.CompletedTask;

    private DateOnly Today => DateOnly.FromDateTime(_clock.Now.LocalDateTime);

    private CultureInfo Culture => CultureInfo.GetCultureInfo(_localization.Language);

    /// <summary>The Monday on or before <paramref name="day"/>.</summary>
    public static DateOnly StartOfWeek(DateOnly day) => day.AddDays(-(((int)day.DayOfWeek + 6) % 7));

    /// <summary>Toggl's duration format: <c>h:mm:ss</c> (hours not padded).</summary>
    public static string FormatDuration(double seconds)
    {
        var time = TimeSpan.FromSeconds(Math.Max(0, Math.Floor(seconds)));
        return string.Create(CultureInfo.InvariantCulture, $"{(int)time.TotalHours}:{time.Minutes:00}:{time.Seconds:00}");
    }

    /// <summary>Reload every loaded week (from the oldest to <see cref="WeekStart"/>'s) in one request.</summary>
    public async Task LoadAsync(CancellationToken cancellationToken = default)
    {
        IsLoading = true;
        Error = null;
        try
        {
            var range = await _client.ListSessionDaysAsync(_oldest, WeekStart.AddDays(6), cancellationToken);
            _days.Clear();
            _days.AddRange(range.Days);
            HasEarlier = range.HasEarlier;
            _storage = range.Storage;
            Render();
        }
        catch (Exception error) when (error is EngineApiException or EngineUnavailableException)
        {
            Error = ErrorText(error);
        }
        finally
        {
            IsLoading = false;
        }
    }

    /// <summary>Rebuild every text after a UI language switch.</summary>
    public void RefreshTexts()
    {
        Render();
        RebuildMatches();
        OnPropertyChanged(nameof(WeekLabel));
    }

    [RelayCommand]
    private Task PreviousWeekAsync() => GoToAsync(WeekStart.AddDays(-7));

    private bool CanGoForward() => !IsThisWeek;

    [RelayCommand(CanExecute = nameof(CanGoForward))]
    private Task NextWeekAsync() => GoToAsync(WeekStart.AddDays(7));

    [RelayCommand(CanExecute = nameof(CanGoForward))]
    private Task ThisWeekAsync() => GoToAsync(StartOfWeek(Today));

    [RelayCommand]
    private Task RefreshAsync() => LoadAsync();

    private bool CanLoadOlder() => HasEarlier && !IsLoading && !IsLoadingOlder;

    /// <summary>Infinite scroll: append the week before the oldest loaded one (skipping empty weeks).</summary>
    [RelayCommand(CanExecute = nameof(CanLoadOlder))]
    private async Task LoadOlderAsync()
    {
        IsLoadingOlder = true;
        try
        {
            for (var week = 0; week < MaxEmptyWeeks && HasEarlier; week++)
            {
                var first = _oldest.AddDays(-7);
                var range = await _client.ListSessionDaysAsync(first, _oldest.AddDays(-1));
                _oldest = first;
                HasEarlier = range.HasEarlier;
                _days.AddRange(range.Days);
                if (range.Days.Count > 0)
                {
                    break;
                }
            }

            Render();
        }
        catch (Exception error) when (error is EngineApiException or EngineUnavailableException)
        {
            Error = ErrorText(error);
        }
        finally
        {
            IsLoadingOlder = false;
        }
    }

    private Task GoToAsync(DateOnly weekStart)
    {
        WeekStart = weekStart;
        _oldest = weekStart;
        Loading = LoadAsync();
        return Loading;
    }

    /// <summary>Rebuild the weeks from the loaded days, leaving out meetings waiting to be deleted.</summary>
    private void Render()
    {
        Weeks.Clear();
        MeetingRow? live = null;
        foreach (var day in _days)
        {
            var rows = new List<MeetingRow>();
            foreach (var summary in day.Items.Where(item => !_hidden.Contains(item.Id)))
            {
                var row = NewRow(summary);
                if (row.IsLive && live is null)
                {
                    live = row; // pinned on top, not in its day
                }
                else
                {
                    rows.Add(row);
                }
            }

            if (rows.Count == 0)
            {
                continue;
            }

            var start = StartOfWeek(day.Date);
            if (Weeks.LastOrDefault() is not { } week || week.Start != start)
            {
                week = new MeetingWeek(start, WeekLabelFor(start), showsHeader: start != WeekStart);
                Weeks.Add(week);
            }

            week.Days.Add(new MeetingDay(day.Date, DayLabel(day.Date), rows));
        }

        Live = live;
        WeekTotal = FormatDuration(_days
            .Where(day => StartOfWeek(day.Date) == WeekStart)
            .SelectMany(day => day.Items)
            .Where(item => !_hidden.Contains(item.Id))
            .Sum(item => item.DurationSeconds ?? 0));
        MarkSelected();
        OnPropertyChanged(nameof(IsEmpty));
    }

    private MeetingRow NewRow(SessionSummary summary)
    {
        var tags = new List<string>();
        if (summary.Template is { } template)
        {
            tags.Add(_templates?.Find(template)?.Name ?? template);
        }

        if (summary.Language is { } code && LanguageKeys.TryGetValue(code, out var key))
        {
            tags.Add(_localization[key]);
        }

        return new MeetingRow(
            summary,
            summary.Title ?? _localization["Untitled"],
            tags,
            TimeRange(summary),
            FormatDuration(summary.DurationSeconds ?? 0),
            _localization.Format("MeetingSpeakers", summary.SpeakerCount),
            [.. ExportFormats.Select(export => (export.Format, _localization[export.LabelKey]))]);
    }

    private string TimeRange(SessionSummary summary)
    {
        if (summary.StartedAt is not { } started)
        {
            return "";
        }

        var live = summary.Status is "recording" or "paused" or "finalizing";
        var ended = summary.EndedAt ?? (!live && summary.DurationSeconds is { } seconds ? started.AddSeconds(seconds) : null);
        var start = started.ToLocalTime().ToString("t", Culture);
        return ended is { } end ? $"{start} – {end.ToLocalTime().ToString("t", Culture)}" : $"{start} –";
    }

    private string DayLabel(DateOnly day)
    {
        var today = Today;
        if (day == today)
        {
            return _localization["MeetingsToday"];
        }

        return day == today.AddDays(-1)
            ? _localization["MeetingsYesterday"]
            : day.ToString("ddd, d MMM", Culture);
    }

    private string WeekLabelFor(DateOnly start)
    {
        var thisWeek = StartOfWeek(Today);
        if (start == thisWeek)
        {
            return _localization["MeetingsThisWeek"];
        }

        return start == thisWeek.AddDays(-7)
            ? _localization["MeetingsLastWeek"]
            : _localization.Format("MeetingsWeekRange", start.ToString("d MMM", Culture), start.AddDays(6).ToString("d MMM", Culture));
    }

    private IEnumerable<MeetingRow> AllRows() =>
        Weeks.SelectMany(week => week.Days).SelectMany(day => day.Rows).Concat(Live is null ? [] : [Live]);

    private void OnHistoryChanged(object? sender, PropertyChangedEventArgs args)
    {
        if (args.PropertyName == nameof(HistoryViewModel.Selected))
        {
            MarkSelected();
        }
    }

    private void MarkSelected()
    {
        var selected = History.Selected?.Id;
        foreach (var row in AllRows().Concat(Matches.Select(match => match.Row).OfType<MeetingRow>()))
        {
            row.IsSelected = row.Id == selected;
        }
    }

    private string ErrorText(Exception error) =>
        error is EngineUnavailableException ? _localization["EngineUnavailable"] : error.Message;
}
