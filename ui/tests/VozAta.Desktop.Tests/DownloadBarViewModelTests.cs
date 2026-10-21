using VozAta.Client;
using VozAta.Desktop.Services;
using VozAta.Desktop.ViewModels;

namespace VozAta.Desktop.Tests;

/// <summary>The bottom bar of phase 42: model downloads with percent and sizes, summed when several run.</summary>
public sealed class DownloadBarViewModelTests
{
    private const long Mb = 1024 * 1024;
    private const long Gb = 1024 * Mb;

    private readonly LocalizationService _localization = new();
    private readonly List<string> _toasts = [];

    private DownloadBarViewModel Create() => new(_localization, _toasts.Add);

    private static DownloadProgressEvent Running(string kind, string model, long done, long? total) =>
        new(null, kind, model, done, total, "running", null);

    [Fact]
    public void Hidden_without_downloads()
    {
        var bar = Create();

        Assert.False(bar.IsVisible);
        Assert.Equal(0, bar.Percent);
        Assert.False(bar.IsIndeterminate);
        Assert.Equal("", bar.Text);
    }

    [Fact]
    public void Shows_kind_model_percent_and_sizes()
    {
        var bar = Create();

        bar.OnProgress(Running("speech", "large-v3-turbo", 720 * Mb, 1440 * Mb));

        Assert.True(bar.IsVisible);
        Assert.False(bar.IsIndeterminate);
        Assert.Equal(50, bar.Percent);
        Assert.Equal("Downloading speech model large-v3-turbo — 50 % (720 MB of 1.4 GB)", bar.Text);
    }

    [Fact]
    public void Gigabytes_use_one_decimal_and_the_language_separator()
    {
        var bar = Create();
        bar.OnProgress(Running("speakers", "community-1", (long)(1.6 * Gb), 2 * Gb));

        Assert.Equal("Downloading speakers model community-1 — 80 % (1.6 GB of 2.0 GB)", bar.Text);

        _localization.SetLanguage("pt-BR");
        bar.RefreshTexts();

        Assert.Equal("Baixando modelo de locutores community-1 — 80 % (1,6 GB de 2,0 GB)", bar.Text);
    }

    [Fact]
    public void Unknown_total_is_indeterminate_with_size_only()
    {
        var bar = Create();

        bar.OnProgress(Running("translation", "ROMANCE-en", 300 * Mb, null));

        Assert.True(bar.IsVisible);
        Assert.True(bar.IsIndeterminate);
        Assert.Equal("Downloading translation model ROMANCE-en — 300 MB", bar.Text);
    }

    [Fact]
    public void Two_downloads_show_one_summed_bar()
    {
        var bar = Create();

        bar.OnProgress(Running("speech", "large-v3", 500 * Mb, 1000 * Mb));
        bar.OnProgress(Running("translation", "ROMANCE-en", 100 * Mb, 1000 * Mb));

        Assert.Equal(30, bar.Percent);
        Assert.Equal("Downloading 2 models — 30 % (600 MB of 2.0 GB)", bar.Text);

        bar.OnProgress(Running("speech", "large-v3", 900 * Mb, 1000 * Mb)); // an update replaces its part

        Assert.Equal(50, bar.Percent);
    }

    [Fact]
    public void Two_downloads_with_an_unknown_total_sum_the_known_part_and_stay_determinate()
    {
        var bar = Create();

        bar.OnProgress(Running("speech", "large-v3", 500 * Mb, 1000 * Mb));
        bar.OnProgress(Running("translation", "ROMANCE-en", 100 * Mb, null));

        Assert.False(bar.IsIndeterminate);
        Assert.Equal(50, bar.Percent);
        Assert.Equal("Downloading 2 models — 50 % (500 MB of 1000 MB)", bar.Text);
    }

    [Fact]
    public void Two_downloads_that_all_have_unknown_totals_are_indeterminate()
    {
        var bar = Create();

        bar.OnProgress(Running("speech", "a", 200 * Mb, null));
        bar.OnProgress(Running("translation", "b", 100 * Mb, null));

        Assert.True(bar.IsIndeterminate);
        Assert.Equal("Downloading 2 models — 300 MB", bar.Text);
    }

    [Fact]
    public void Done_removes_its_part_and_hides_when_empty()
    {
        var bar = Create();
        bar.OnProgress(Running("speech", "large-v3", 500 * Mb, 1000 * Mb));
        bar.OnProgress(Running("translation", "ROMANCE-en", 100 * Mb, 200 * Mb));

        bar.OnProgress(new DownloadProgressEvent(null, "speech", "large-v3", 1000 * Mb, 1000 * Mb, "done", null));

        Assert.True(bar.IsVisible);
        Assert.Equal("Downloading translation model ROMANCE-en — 50 % (100 MB of 200 MB)", bar.Text);

        bar.OnProgress(new DownloadProgressEvent(null, "translation", "ROMANCE-en", 200 * Mb, 200 * Mb, "done", null));

        Assert.False(bar.IsVisible);
        Assert.Empty(_toasts);
    }

    [Fact]
    public void Failed_hides_and_raises_a_toast()
    {
        var bar = Create();
        bar.OnProgress(Running("speech", "large-v3", 500 * Mb, 1000 * Mb));

        bar.OnProgress(new DownloadProgressEvent(null, "speech", "large-v3", 500 * Mb, 1000 * Mb, "failed", "no network"));

        Assert.False(bar.IsVisible);
        Assert.Equal(["Downloading the speech model large-v3 failed: no network"], _toasts);
    }

    [Fact]
    public void Failed_without_a_reason_still_raises_a_toast()
    {
        var bar = Create();

        bar.OnProgress(new DownloadProgressEvent(null, "speakers", "community-1", 0, null, "failed", null));

        Assert.Single(_toasts);
        Assert.StartsWith("Downloading the speakers model community-1 failed:", _toasts[0]);
    }

    [Fact]
    public void An_unknown_state_is_ignored()
    {
        var bar = Create();

        bar.OnProgress(new DownloadProgressEvent(null, "speech", "x", 1, 2, "paused", null));

        Assert.False(bar.IsVisible);
    }

    [Fact]
    public void Connection_lost_clears()
    {
        var bar = Create();
        bar.OnProgress(Running("speech", "large-v3", 500 * Mb, 1000 * Mb));

        bar.OnConnectionLost();

        Assert.False(bar.IsVisible);
        Assert.Equal("", bar.Text);
        Assert.Equal(0, bar.Percent);
    }

    [Fact]
    public void Language_change_refreshes_the_text()
    {
        var bar = Create();
        bar.OnProgress(Running("speech", "large-v3", 500 * Mb, 1000 * Mb));

        _localization.SetLanguage("es");
        bar.RefreshTexts();

        Assert.Equal("Descargando modelo de voz large-v3 — 50 % (500 MB de 1000 MB)", bar.Text);

        _localization.SetLanguage("pt-BR");
        bar.RefreshTexts();

        Assert.Equal("Baixando modelo de fala large-v3 — 50 % (500 MB de 1000 MB)", bar.Text);
    }

    [Fact]
    public void Unknown_kinds_are_shown_as_sent()
    {
        var bar = Create();

        bar.OnProgress(Running("vision", "m", 10 * Mb, null));

        Assert.Equal("Downloading vision model m — 10 MB", bar.Text);
    }
}
