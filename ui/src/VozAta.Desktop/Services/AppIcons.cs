using VozAta.Desktop.ViewModels;

namespace VozAta.Desktop.Services;

/// <summary>
/// Where the app and tray icons live. Idle shows the VozAta logo; recording and paused keep their
/// own red and amber icons so the recording state stays obvious at a glance.
/// </summary>
public static class AppIcons
{
    private const string AssetRoot = "avares://VozAta.Desktop/Assets/";

    /// <summary>The VozAta logo (multi-size .ico) used by every window and the idle tray.</summary>
    public static Uri Logo { get; } = new(AssetRoot + "vozata.ico");

    /// <summary>The tray icon for a recording state.</summary>
    public static Uri ForTray(TrayState state) => state switch
    {
        TrayState.Recording => new Uri(AssetRoot + "tray-recording.png"),
        TrayState.Paused => new Uri(AssetRoot + "tray-paused.png"),
        _ => Logo,
    };
}
