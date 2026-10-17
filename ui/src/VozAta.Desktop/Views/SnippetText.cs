using System.Diagnostics.CodeAnalysis;
using Avalonia;
using Avalonia.Controls;
using Avalonia.Controls.Documents;
using Avalonia.Media;
using VozAta.Desktop.ViewModels;

namespace VozAta.Desktop.Views;

/// <summary>Shows search snippet parts in a <see cref="TextBlock"/>, matches in bold and highlighted.</summary>
[ExcludeFromCodeCoverage(Justification = "View behavior; parsing is tested in SnippetPart.")]
public static class SnippetText
{
    public static readonly AttachedProperty<IReadOnlyList<SnippetPart>?> PartsProperty =
        AvaloniaProperty.RegisterAttached<TextBlock, IReadOnlyList<SnippetPart>?>("Parts", typeof(SnippetText));

    private static readonly IBrush MatchBackground = new SolidColorBrush(Color.FromArgb(0x66, 0xFF, 0xD5, 0x4F));

    static SnippetText()
    {
        PartsProperty.Changed.AddClassHandler<TextBlock>((block, args) =>
        {
            var inlines = new InlineCollection();
            foreach (var part in args.GetNewValue<IReadOnlyList<SnippetPart>?>() ?? [])
            {
                inlines.Add(part.IsMatch
                    ? new Run(part.Text) { FontWeight = FontWeight.Bold, Background = MatchBackground }
                    : new Run(part.Text));
            }

            block.Inlines = inlines;
        });
    }

    public static IReadOnlyList<SnippetPart>? GetParts(TextBlock block) => block.GetValue(PartsProperty);

    public static void SetParts(TextBlock block, IReadOnlyList<SnippetPart>? value) => block.SetValue(PartsProperty, value);
}
