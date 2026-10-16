using VozAta.Desktop.ViewModels;

namespace VozAta.Desktop.Tests;

public sealed class MarkdownBlocksTests
{
    [Fact]
    public void Minutes_become_headings_items_and_paragraphs()
    {
        const string markdown = """
            # Minutes

            ## Summary
            The team **agreed** to delay the beta.
            It ships on Tuesday.

            ## Decisions
            - Beta moves to *Tuesday*
            * Carlos fixes the tests

            ### Action items
            1. Ana updates the release notes
            2) Decide on macOS
            """;

        var blocks = MarkdownBlocks.Parse(markdown);

        Assert.Equal(
            [
                new MarkdownBlock(MarkdownBlockKind.Heading1, "Minutes"),
                new MarkdownBlock(MarkdownBlockKind.Heading2, "Summary"),
                new MarkdownBlock(MarkdownBlockKind.Paragraph, "The team agreed to delay the beta. It ships on Tuesday."),
                new MarkdownBlock(MarkdownBlockKind.Heading2, "Decisions"),
                new MarkdownBlock(MarkdownBlockKind.Bullet, "Beta moves to Tuesday"),
                new MarkdownBlock(MarkdownBlockKind.Bullet, "Carlos fixes the tests"),
                new MarkdownBlock(MarkdownBlockKind.Heading3, "Action items"),
                new MarkdownBlock(MarkdownBlockKind.Numbered, "1. Ana updates the release notes"),
                new MarkdownBlock(MarkdownBlockKind.Numbered, "2. Decide on macOS"),
            ],
            blocks);
    }

    [Theory]
    [InlineData("")]
    [InlineData("   \n\n  ")]
    public void Empty_text_has_no_blocks(string markdown)
    {
        Assert.Empty(MarkdownBlocks.Parse(markdown));
    }

    [Fact]
    public void Deeper_headings_and_windows_line_endings_are_handled()
    {
        var blocks = MarkdownBlocks.Parse("#### Notes\r\n- a **b** c\r\n\r\ntext");

        Assert.Equal(
            [
                new MarkdownBlock(MarkdownBlockKind.Heading3, "Notes"),
                new MarkdownBlock(MarkdownBlockKind.Bullet, "a b c"),
                new MarkdownBlock(MarkdownBlockKind.Paragraph, "text"),
            ],
            blocks);
    }

    [Fact]
    public void Lines_that_only_look_like_markup_stay_text()
    {
        var blocks = MarkdownBlocks.Parse("#hashtag\n2026 was a good year\n-dash");

        Assert.Equal([new MarkdownBlock(MarkdownBlockKind.Paragraph, "#hashtag 2026 was a good year -dash")], blocks);
    }
}
