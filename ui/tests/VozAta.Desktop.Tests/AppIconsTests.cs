using Avalonia.Platform;
using VozAta.Desktop.Services;
using VozAta.Desktop.ViewModels;

namespace VozAta.Desktop.Tests;

public sealed class AppIconsTests
{
    [Fact]
    public void Idle_tray_shows_the_logo()
    {
        Assert.Equal(AppIcons.Logo, AppIcons.ForTray(TrayState.Idle));
    }

    [Fact]
    public void Recording_and_paused_keep_their_own_icons()
    {
        var recording = AppIcons.ForTray(TrayState.Recording);
        var paused = AppIcons.ForTray(TrayState.Paused);

        Assert.EndsWith("tray-recording.png", recording.AbsolutePath, StringComparison.Ordinal);
        Assert.EndsWith("tray-paused.png", paused.AbsolutePath, StringComparison.Ordinal);
        Assert.NotEqual(AppIcons.Logo, recording);
        Assert.NotEqual(AppIcons.Logo, paused);
        Assert.NotEqual(recording, paused);
    }

    [Fact]
    public void Every_icon_is_an_embedded_resource()
    {
        var uris = Enum.GetValues<TrayState>().Select(AppIcons.ForTray)
            .Append(AppIcons.Logo)
            .Append(new Uri("avares://VozAta.Desktop/Assets/vozata-64.png"));

        var loader = new StandardAssetLoader();
        Assert.All(uris, uri => Assert.True(loader.Exists(uri), $"missing asset {uri}"));
    }
}
