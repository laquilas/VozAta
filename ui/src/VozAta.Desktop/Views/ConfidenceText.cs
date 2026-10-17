using System.Diagnostics.CodeAnalysis;
using Avalonia;
using Avalonia.Controls;
using Avalonia.Controls.Documents;
using Avalonia.Media;
using VozAta.Desktop.ViewModels;

namespace VozAta.Desktop.Views;

/// <summary>Shows transcript text parts in a <see cref="TextBlock"/>, low-confidence words highlighted (phase 21).</summary>
[ExcludeFromCodeCoverage(Justification = "View behavior; the split is tested in LowConfidence.")]
public static class ConfidenceText
{
    public static readonly AttachedProperty<IReadOnlyList<TextPart>?> PartsProperty =
        AvaloniaProperty.RegisterAttached<TextBlock, IReadOnlyList<TextPart>?>("Parts", typeof(ConfidenceText));

    private static readonly IBrush LowConfidenceBackground = new SolidColorBrush(Color.FromArgb(0x55, 0xFF, 0x98, 0x00));

    static ConfidenceText()
    {
        PartsProperty.Changed.AddClassHandler<TextBlock>((block, args) =>
        {
            var inlines = new InlineCollection();
            foreach (var part in args.GetNewValue<IReadOnlyList<TextPart>?>() ?? [])
            {
                inlines.Add(part.IsLowConfidence
                    ? new Run(part.Text) { Background = LowConfidenceBackground, TextDecorations = TextDecorations.Underline }
                    : new Run(part.Text));
            }

            block.Inlines = inlines;
        });
    }

    public static IReadOnlyList<TextPart>? GetParts(TextBlock block) => block.GetValue(PartsProperty);

    public static void SetParts(TextBlock block, IReadOnlyList<TextPart>? value) => block.SetValue(PartsProperty, value);
}
