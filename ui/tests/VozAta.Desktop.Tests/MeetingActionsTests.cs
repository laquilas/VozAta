using Avalonia.Controls;
using Avalonia.Headless;
using Avalonia.Threading;
using VozAta.Desktop.ViewModels;
using VozAta.Desktop.Views;

namespace VozAta.Desktop.Tests;

/// <summary>
/// The meeting page groups its actions: template + regenerate, an Export menu and a "more actions"
/// menu. The menus open in a popup, so their localized labels and commands are checked opened.
/// </summary>
public sealed class MeetingActionsTests
{
    [Theory]
    [InlineData("light")]
    [InlineData("dark")]
    public async Task The_header_shows_chips_and_the_menus_carry_every_action(string theme)
    {
        var menus = await ThemeRenderTests.Session.Value.Dispatch<Dictionary<string, List<(string Header, bool HasCommand)>>>(
            async () =>
            {
                var (viewModel, _) = await ThemeRenderTests.SeededAsync(theme);
                viewModel.History.Selected = viewModel.History.Rows[0];
                await viewModel.History.DetailLoading;
                var window = new MainWindow { DataContext = viewModel, Width = 1024, Height = 720 };
                window.Show();
                try
                {
                    Dispatcher.UIThread.RunJobs();
                    var page = window.GetVisualDescendant<SessionPage>();
                    var actions = Avalonia.VisualTree.VisualExtensions.GetVisualDescendants(page)
                        .OfType<WrapPanel>().Single(panel => panel.Classes.Contains("meeting-actions"));
                    Assert.Equal(4, actions.Children.Count(child => child.IsVisible)); // template, regenerate, export, more

                    var result = new Dictionary<string, List<(string, bool)>>();
                    foreach (var button in actions.Children.OfType<Button>().Where(button => button.Flyout is MenuFlyout))
                    {
                        var flyout = (MenuFlyout)button.Flyout!;
                        flyout.ShowAt(button);
                        Dispatcher.UIThread.RunJobs();
                        SaveFrame(window, $"meeting-menu-{result.Count}-{theme}.png");
                        result[Avalonia.Automation.AutomationProperties.GetName(button)!] = flyout.Items.OfType<MenuItem>()
                            .Where(item => item.IsVisible)
                            .Select(item => ((string)item.Header!, item.Command is not null))
                            .ToList();
                        flyout.Hide();
                        Dispatcher.UIThread.RunJobs();
                    }

                    return result;
                }
                finally
                {
                    window.Close();
                }
            },
            CancellationToken.None);

        Assert.Equal(
            [("Export Markdown", true), ("Export Word", true), ("Export PDF", true), ("Export recording (.zip)", true)],
            menus["Export"]);
        Assert.Equal([("Open in external player", true), ("Delete audio", true)], menus["More actions"]);
    }

    private static void SaveFrame(Window window, string name)
    {
        var folder = Environment.GetEnvironmentVariable("VOZATA_SCREENSHOTS");
        if (!string.IsNullOrEmpty(folder))
        {
            Directory.CreateDirectory(folder);
            window.CaptureRenderedFrame()?.Save(Path.Combine(folder, name), Avalonia.Media.Imaging.PngBitmapEncoderOptions.Default);
        }
    }
}
