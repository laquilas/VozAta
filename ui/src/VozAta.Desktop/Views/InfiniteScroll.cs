using System.Diagnostics.CodeAnalysis;
using System.Windows.Input;
using Avalonia;
using Avalonia.Controls;

namespace VozAta.Desktop.Views;

/// <summary>
/// Runs <c>Command</c> when a <see cref="ScrollViewer"/> gets near its end, or when its content does
/// not fill it (the Meetings page loads older weeks this way, phase 36).
/// </summary>
[ExcludeFromCodeCoverage(Justification = "View behavior; verified in the manual check.")]
public static class InfiniteScroll
{
    /// <summary>How close to the end (in pixels) the next page is asked for.</summary>
    public const double Threshold = 240;

    public static readonly AttachedProperty<ICommand?> CommandProperty =
        AvaloniaProperty.RegisterAttached<ScrollViewer, ICommand?>("Command", typeof(InfiniteScroll));

    static InfiniteScroll()
    {
        CommandProperty.Changed.AddClassHandler<ScrollViewer>((viewer, args) =>
        {
            viewer.ScrollChanged -= OnScrollChanged;
            if (args.NewValue is ICommand)
            {
                viewer.ScrollChanged += OnScrollChanged;
            }
        });
    }

    public static ICommand? GetCommand(ScrollViewer viewer) => viewer.GetValue(CommandProperty);

    public static void SetCommand(ScrollViewer viewer, ICommand? value) => viewer.SetValue(CommandProperty, value);

    private static void OnScrollChanged(object? sender, ScrollChangedEventArgs args)
    {
        if (sender is not ScrollViewer viewer || GetCommand(viewer) is not { } command)
        {
            return;
        }

        var nearEnd = viewer.Offset.Y + viewer.Viewport.Height >= viewer.Extent.Height - Threshold;
        if (nearEnd && command.CanExecute(null))
        {
            command.Execute(null);
        }
    }
}
