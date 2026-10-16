using System.Text;
using System.Text.RegularExpressions;

namespace VozAta.Desktop.ViewModels;

public enum MarkdownBlockKind
{
    Heading1,
    Heading2,
    Heading3,
    Paragraph,
    Bullet,
    Numbered,
}

/// <summary>One displayable block of the minutes; the flags let the view pick a style.</summary>
public sealed record MarkdownBlock(MarkdownBlockKind Kind, string Text)
{
    public bool IsHeading1 => Kind == MarkdownBlockKind.Heading1;

    public bool IsHeading2 => Kind == MarkdownBlockKind.Heading2;

    public bool IsHeading3 => Kind == MarkdownBlockKind.Heading3;

    public bool IsItem => Kind is MarkdownBlockKind.Bullet or MarkdownBlockKind.Numbered;

    public string Display => Kind == MarkdownBlockKind.Bullet ? $"• {Text}" : Text;
}

/// <summary>
/// The Markdown subset our minutes prompt produces — headings, bullet and numbered items,
/// paragraphs — as display blocks. Emphasis markers are dropped (no package supports Avalonia 12
/// yet; see phase 09 notes).
/// </summary>
public static partial class MarkdownBlocks
{
    public static IReadOnlyList<MarkdownBlock> Parse(string markdown)
    {
        var blocks = new List<MarkdownBlock>();
        var paragraph = new StringBuilder();

        void EndParagraph()
        {
            if (paragraph.Length > 0)
            {
                blocks.Add(new MarkdownBlock(MarkdownBlockKind.Paragraph, paragraph.ToString()));
                paragraph.Clear();
            }
        }

        foreach (var raw in markdown.ReplaceLineEndings("\n").Split('\n'))
        {
            var line = raw.Trim();
            if (line.Length == 0)
            {
                EndParagraph();
                continue;
            }

            if (Heading().Match(line) is { Success: true } heading)
            {
                EndParagraph();
                var kind = heading.Groups[1].Length switch
                {
                    1 => MarkdownBlockKind.Heading1,
                    2 => MarkdownBlockKind.Heading2,
                    _ => MarkdownBlockKind.Heading3,
                };
                blocks.Add(new MarkdownBlock(kind, Clean(heading.Groups[2].Value)));
            }
            else if (Bullet().Match(line) is { Success: true } bullet)
            {
                EndParagraph();
                blocks.Add(new MarkdownBlock(MarkdownBlockKind.Bullet, Clean(bullet.Groups[1].Value)));
            }
            else if (Numbered().Match(line) is { Success: true } numbered)
            {
                EndParagraph();
                var text = $"{numbered.Groups[1].Value}. {Clean(numbered.Groups[2].Value)}";
                blocks.Add(new MarkdownBlock(MarkdownBlockKind.Numbered, text));
            }
            else
            {
                paragraph.Append(paragraph.Length > 0 ? " " : "").Append(Clean(line));
            }
        }

        EndParagraph();
        return blocks;
    }

    private static string Clean(string text) => Emphasis().Replace(text, "").Trim();

    [GeneratedRegex(@"^(#{1,6})\s+(.+)$")]
    private static partial Regex Heading();

    [GeneratedRegex(@"^[-*+]\s+(.+)$")]
    private static partial Regex Bullet();

    [GeneratedRegex(@"^(\d+)[.)]\s+(.+)$")]
    private static partial Regex Numbered();

    [GeneratedRegex(@"\*\*|__|(?<![\w*])\*(?=\S)|(?<=\S)\*(?![\w*])")]
    private static partial Regex Emphasis();
}
