using Avalonia;
using Avalonia.Controls;
using Avalonia.Threading;
using VozAta.Client;
using VozAta.Desktop.Tests.Fakes;
using VozAta.Desktop.ViewModels;
using VozAta.Desktop.Views;

namespace VozAta.Desktop.Tests;

/// <summary>Long status lines wrap inside the sidebar instead of running over the page.</summary>
public sealed class SidebarLayoutTests
{
    [Fact]
    public async Task The_engine_status_stays_inside_the_sidebar()
    {
        var overflow = await ThemeRenderTests.Session.Value.Dispatch<double>(
            async () =>
            {
                var events = new FakeEngineEvents();
                var (viewModel, _) = await ThemeRenderTests.SeededAsync("light", events: events);
                var handled = viewModel.HandledEvents;
                events.Send(new ConnectionChangedEvent(false)); // "Engine disconnected, reconnecting…"
                for (var i = 0; i < 200 && viewModel.HandledEvents == handled; i++)
                {
                    await Task.Delay(5);
                }

                Assert.True(viewModel.IsEngineDown);
                var window = new MainWindow { DataContext = viewModel, Width = 1280, Height = 860 };
                window.Show();
                try
                {
                    Dispatcher.UIThread.RunJobs();
                    var sidebar = Avalonia.VisualTree.VisualExtensions.GetVisualDescendants(window).OfType<Border>().First(border => border.Classes.Contains("sidebar"));
                    var status = Avalonia.VisualTree.VisualExtensions.GetVisualDescendants(window).OfType<TextBlock>().First(text => text.Text == viewModel.EngineText);
                    var right = status.TranslatePoint(new Point(status.Bounds.Width, 0), sidebar)!.Value.X;
                    return right - sidebar.Bounds.Width;
                }
                finally
                {
                    window.Close();
                }
            },
            CancellationToken.None);

        Assert.True(overflow <= 0, $"the engine status runs {overflow:0} px past the sidebar");
    }
}
