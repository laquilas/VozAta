using System.Diagnostics.CodeAnalysis;
using Avalonia;
using Avalonia.Controls;

namespace VozAta.Desktop.Views;

/// <summary>
/// Keeps a <see cref="ScrollViewer"/> pinned to the bottom while content grows, unless the user
/// scrolled up to read earlier lines.
/// </summary>
[ExcludeFromCodeCoverage(Justification = "View behavior; verified in the manual check.")]
public static class AutoScroll
{
    public static readonly AttachedProperty<bool> IsEnabledProperty =
        AvaloniaProperty.RegisterAttached<ScrollViewer, bool>("IsEnabled", typeof(AutoScroll));

    static AutoScroll()
    {
        IsEnabledProperty.Changed.AddClassHandler<ScrollViewer>((viewer, args) =>
        {
            if (args.NewValue is true)
            {
                viewer.PropertyChanged += OnPropertyChanged;
            }
            else
            {
                viewer.PropertyChanged -= OnPropertyChanged;
            }
        });
    }

    public static bool GetIsEnabled(ScrollViewer viewer) => viewer.GetValue(IsEnabledProperty);

    public static void SetIsEnabled(ScrollViewer viewer, bool value) => viewer.SetValue(IsEnabledProperty, value);

    private static void OnPropertyChanged(object? sender, AvaloniaPropertyChangedEventArgs args)
    {
        if (sender is not ScrollViewer viewer || args.Property != ScrollViewer.ExtentProperty)
        {
            return;
        }

        var previous = args.GetOldValue<Size>();
        var wasAtBottom = viewer.Offset.Y + viewer.Viewport.Height >= previous.Height - 24;
        if (wasAtBottom)
        {
            viewer.ScrollToEnd();
        }
    }
}
