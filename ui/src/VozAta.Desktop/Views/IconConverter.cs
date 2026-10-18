using System.Globalization;
using Avalonia;
using Avalonia.Controls;
using Avalonia.Data.Converters;
using Avalonia.Media;

namespace VozAta.Desktop.Views;

/// <summary>
/// An icon resource key (<c>Icon.Record</c>, see Icons.axaml) to its geometry, so ViewModels name
/// icons without holding Avalonia types (sidebar pages, phase 35).
/// </summary>
public sealed class IconConverter : IValueConverter
{
    public static readonly IconConverter Instance = new();

    public object? Convert(object? value, Type targetType, object? parameter, CultureInfo culture) =>
        value is string key && Application.Current?.TryFindResource(key, out var resource) == true
            ? resource as Geometry
            : null;

    public object? ConvertBack(object? value, Type targetType, object? parameter, CultureInfo culture) =>
        throw new NotSupportedException();
}
