using System.Globalization;
using CommunityToolkit.Mvvm.ComponentModel;
using VozAta.Client;
using VozAta.Desktop.Services;

namespace VozAta.Desktop.ViewModels;

/// <summary>
/// The bar at the bottom of the page area while models download (phase 42): the label centered over
/// the progress. One download shows its kind, model, percent and sizes; several show one summed bar.
/// A failed download leaves the bar and raises a toast.
/// </summary>
public sealed partial class DownloadBarViewModel(ILocalizationService localization, Action<string> notify)
    : ObservableObject
{
    private const long Megabyte = 1024 * 1024;
    private const long Gigabyte = 1024 * Megabyte;

    private readonly Dictionary<(string Kind, string Model), DownloadProgressEvent> _running = [];

    public bool IsVisible => _running.Count > 0;

    /// <summary>0-100; the known part of the downloads (the sizes of unknown totals are left out).</summary>
    [ObservableProperty]
    public partial double Percent { get; private set; }

    /// <summary>Every running download has an unknown total, so the bar only shows activity.</summary>
    [ObservableProperty]
    public partial bool IsIndeterminate { get; private set; }

    [ObservableProperty]
    public partial string Text { get; private set; } = "";

    public void OnProgress(DownloadProgressEvent progress)
    {
        var key = (progress.Kind, progress.Model);
        switch (progress.State)
        {
            case "running":
                _running[key] = progress;
                break;
            case "done":
                _running.Remove(key);
                break;
            case "failed":
                _running.Remove(key);
                notify(localization.Format(
                    "DownloadFailed", KindName(progress.Kind), progress.Model, progress.Reason ?? ""));
                break;
            default:
                return;
        }

        Update();
    }

    /// <summary>The engine went away: hide the bar (a restarted engine reports its downloads again).</summary>
    public void OnConnectionLost()
    {
        _running.Clear();
        Update();
    }

    public void RefreshTexts() => Update();

    private void Update()
    {
        OnPropertyChanged(nameof(IsVisible));
        if (_running.Count == 0)
        {
            Percent = 0;
            IsIndeterminate = false;
            Text = "";
            return;
        }

        var all = _running.Values.ToList();
        var known = all.Where(download => download.TotalBytes is not null).ToList();
        var done = known.Sum(download => download.DownloadedBytes);
        var total = known.Sum(download => download.TotalBytes!.Value);
        Percent = total > 0 ? Math.Clamp(100.0 * done / total, 0, 100) : 0;
        IsIndeterminate = known.Count == 0;
        var percent = ((int)Math.Round(Percent)).ToString(CultureInfo.InvariantCulture);
        if (all.Count > 1)
        {
            Text = known.Count == 0
                ? localization.Format("DownloadManyUnknown", all.Count, Size(all.Sum(download => download.DownloadedBytes)))
                : localization.Format("DownloadMany", all.Count, percent, Size(done), Size(total));
            return;
        }

        var single = all[0];
        Text = single.TotalBytes is null
            ? localization.Format("DownloadUnknown", KindName(single.Kind), single.Model, Size(single.DownloadedBytes))
            : localization.Format(
                "DownloadOne", KindName(single.Kind), single.Model, percent, Size(done), Size(total));
    }

    private string KindName(string kind) => kind switch
    {
        "speech" => localization["DownloadKindSpeech"],
        "speakers" => localization["DownloadKindSpeakers"],
        "translation" => localization["DownloadKindTranslation"],
        _ => kind,
    };

    /// <summary>MB without decimals below 1 GB, GB with one decimal, in the interface language.</summary>
    private string Size(long bytes)
    {
        var culture = CultureInfo.GetCultureInfo(localization.Language);
        return bytes < Gigabyte
            ? string.Create(culture, $"{Math.Round((double)bytes / Megabyte):0} MB")
            : string.Create(culture, $"{(double)bytes / Gigabyte:0.0} GB");
    }
}
