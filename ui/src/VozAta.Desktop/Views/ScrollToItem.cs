using System.Diagnostics.CodeAnalysis;
using Avalonia;
using Avalonia.Controls;
using Avalonia.Threading;

namespace VozAta.Desktop.Views;

/// <summary>Scrolls an <see cref="ItemsControl"/>'s bound item into view once it is laid out.</summary>
[ExcludeFromCodeCoverage(Justification = "View behavior; verified in the manual check.")]
public static class ScrollToItem
{
    public static readonly AttachedProperty<object?> ItemProperty =
        AvaloniaProperty.RegisterAttached<ItemsControl, object?>("Item", typeof(ScrollToItem));

    static ScrollToItem()
    {
        ItemProperty.Changed.AddClassHandler<ItemsControl>((items, args) =>
        {
            if (args.NewValue is { } item)
            {
                // After layout: a tab that just opened has no containers yet.
                Dispatcher.UIThread.Post(() => items.ContainerFromItem(item)?.BringIntoView(), DispatcherPriority.Background);
            }
        });
    }

    public static object? GetItem(ItemsControl items) => items.GetValue(ItemProperty);

    public static void SetItem(ItemsControl items, object? value) => items.SetValue(ItemProperty, value);
}
