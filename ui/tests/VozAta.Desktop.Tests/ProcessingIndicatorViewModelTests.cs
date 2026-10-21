using VozAta.Client;
using VozAta.Desktop.Services;
using VozAta.Desktop.ViewModels;

namespace VozAta.Desktop.Tests;

public sealed class ProcessingIndicatorViewModelTests
{
    private readonly LocalizationService _localization = new();

    private ProcessingIndicatorViewModel Create() => new(_localization);

    private static ProcessingEvent Event(string id, string state, int percent = 0, int? position = null) =>
        new(id, new ProcessingInfo(state, percent, null, position));

    [Fact]
    public void Indicator_hidden_when_queue_empty()
    {
        var indicator = Create();

        Assert.False(indicator.IsVisible);
        Assert.Equal(0, indicator.PendingCount);
        Assert.Equal("", indicator.Text);
        Assert.Equal("", indicator.QueuedText);
    }

    [Fact]
    public void Indicator_shows_running_percent_and_queued_count()
    {
        var indicator = Create();

        indicator.OnProcessing(Event("a", "running", 42));
        indicator.OnProcessing(Event("b", "queued", position: 1));
        indicator.OnProcessing(Event("c", "queued", position: 2));

        Assert.True(indicator.IsVisible);
        Assert.Equal(3, indicator.PendingCount);
        Assert.Equal("Processing 1 meeting · 42 %", indicator.Text);
        Assert.Equal("+2 queued", indicator.QueuedText);
        Assert.True(indicator.HasRunning);
        Assert.True(indicator.HasQueued);
    }

    [Fact]
    public void A_paused_meeting_counts_as_the_running_one()
    {
        var indicator = Create();

        indicator.OnProcessing(Event("a", "paused", 30));

        Assert.Equal("Processing 1 meeting · 30 %", indicator.Text);
        Assert.False(indicator.HasQueued);
        Assert.Equal("", indicator.QueuedText);
    }

    [Fact]
    public void With_only_queued_meetings_only_the_queued_line_shows()
    {
        var indicator = Create();

        indicator.OnProcessing(Event("a", "queued", position: 1));

        Assert.True(indicator.IsVisible);
        Assert.False(indicator.HasRunning);
        Assert.Equal("", indicator.Text);
        Assert.Equal("+1 queued", indicator.QueuedText);
    }

    [Fact]
    public void Done_and_failed_meetings_leave_the_count()
    {
        var indicator = Create();
        indicator.OnProcessing(Event("a", "running", 90));
        indicator.OnProcessing(Event("b", "queued", position: 1));

        indicator.OnProcessing(Event("a", "done", 100));
        Assert.Equal(1, indicator.PendingCount);
        indicator.OnProcessing(Event("b", "failed"));

        Assert.False(indicator.IsVisible);
    }

    [Fact]
    public void The_tooltip_joins_both_lines_and_skips_empty_ones()
    {
        var indicator = Create();
        indicator.OnProcessing(Event("b", "queued", position: 1));
        Assert.Equal("+1 queued", indicator.ToolTipText);

        indicator.OnProcessing(Event("a", "running", 5));
        Assert.Equal("Processing 1 meeting · 5 %\n+1 queued", indicator.ToolTipText);
    }

    [Fact]
    public void Events_without_a_session_are_ignored()
    {
        var indicator = Create();

        indicator.OnProcessing(new ProcessingEvent(null, new ProcessingInfo("running", 10, null)));

        Assert.False(indicator.IsVisible);
    }

    [Fact]
    public void Clear_empties_the_indicator_and_notifies()
    {
        var indicator = Create();
        indicator.OnProcessing(Event("a", "running", 10));
        var changed = new List<string?>();
        indicator.PropertyChanged += (_, args) => changed.Add(args.PropertyName);

        indicator.Clear();

        Assert.False(indicator.IsVisible);
        Assert.Contains(nameof(ProcessingIndicatorViewModel.IsVisible), changed);
    }

    [Fact]
    public void Two_active_meetings_use_the_plural()
    {
        var indicator = Create();
        indicator.OnProcessing(Event("a", "running", 40));
        indicator.OnProcessing(Event("b", "paused", 10));

        Assert.Equal("Processing 2 meetings · 40 %", indicator.Text);

        _localization.SetLanguage("pt-BR");
        indicator.RefreshTexts();
        Assert.Equal("Processando 2 reuniões · 40 %", indicator.Text);
    }

    [Fact]
    public void Texts_follow_the_language()
    {
        var indicator = Create();
        indicator.OnProcessing(Event("a", "running", 5));
        indicator.OnProcessing(Event("b", "queued", position: 1));

        _localization.SetLanguage("pt-BR");
        indicator.RefreshTexts();

        Assert.Equal("Processando 1 reunião · 5 %", indicator.Text);
        Assert.Equal("+1 na fila", indicator.QueuedText);
    }
}
