using System.Diagnostics.CodeAnalysis;
using Avalonia.Controls;
using Avalonia.Controls.ApplicationLifetimes;
using Avalonia.Layout;

namespace VozAta.Desktop.Services;

/// <summary>Confirmation dialogs as small modal windows owned by the main window.</summary>
[ExcludeFromCodeCoverage(Justification = "Avalonia windows; covered by the manual check.")]
public sealed class AvaloniaDialogService(IClassicDesktopStyleApplicationLifetime lifetime) : IDialogService
{
    public async Task<bool> ConfirmAsync(string title, string message, string confirm, string cancel)
    {
        var dialog = new Window
        {
            Title = title,
            Icon = lifetime.MainWindow?.Icon,
            Width = 460,
            SizeToContent = SizeToContent.Height,
            CanResize = false,
            WindowStartupLocation = WindowStartupLocation.CenterOwner,
        };
        var yes = new Button { Content = confirm, Classes = { "accent" } };
        var no = new Button { Content = cancel, IsDefault = true, IsCancel = true };
        yes.Click += (_, _) => dialog.Close(true);
        no.Click += (_, _) => dialog.Close(false);
        dialog.Content = new StackPanel
        {
            Margin = new Avalonia.Thickness(20),
            Spacing = 16,
            Children =
            {
                new TextBlock { Text = message, TextWrapping = Avalonia.Media.TextWrapping.Wrap },
                new StackPanel
                {
                    Orientation = Orientation.Horizontal,
                    HorizontalAlignment = HorizontalAlignment.Right,
                    Spacing = 8,
                    Children = { no, yes },
                },
            },
        };
        return lifetime.MainWindow is { } owner && await dialog.ShowDialog<bool>(owner);
    }
}
