using VozAta.Client;

namespace VozAta.Desktop.ViewModels;

/// <summary>A piece of transcript text; low-confidence words are highlighted in read mode (phase 21).</summary>
public sealed record TextPart(string Text, bool IsLowConfidence = false);

/// <summary>Splits a segment's text around words recognized with low probability.</summary>
public static class LowConfidence
{
    /// <summary>Used until <c>LOW_CONFIDENCE_THRESHOLD</c> is read from the engine (its default).</summary>
    public const double DefaultThreshold = 0.5;

    /// <summary>
    /// The text in parts, words with <c>probability &lt; threshold</c> marked; null when no word is
    /// below it (show the plain text). Words are matched in order; a word not found in the text
    /// (e.g. after an edit) is skipped.
    /// </summary>
    public static IReadOnlyList<TextPart>? Split(string text, IReadOnlyList<Word> words, double threshold)
    {
        var parts = new List<TextPart>();
        var cursor = 0;
        var plainStart = 0;
        foreach (var word in words)
        {
            var token = word.Text.Trim();
            var at = token.Length == 0 ? -1 : text.IndexOf(token, cursor, StringComparison.Ordinal);
            if (at < 0)
            {
                continue;
            }

            cursor = at + token.Length;
            if (word.Probability >= threshold)
            {
                continue;
            }

            if (at > plainStart)
            {
                parts.Add(new TextPart(text[plainStart..at]));
            }

            parts.Add(new TextPart(token, IsLowConfidence: true));
            plainStart = cursor;
        }

        if (parts.Count == 0)
        {
            return null;
        }

        if (plainStart < text.Length)
        {
            parts.Add(new TextPart(text[plainStart..]));
        }

        return parts;
    }
}
