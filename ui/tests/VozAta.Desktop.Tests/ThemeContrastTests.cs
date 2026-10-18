using System.Globalization;
using System.Xml.Linq;

namespace VozAta.Desktop.Tests;

/// <summary>
/// Text drawn by the views stays readable (phase 34): every text/background pair of the design tokens
/// has a WCAG 2 contrast ratio of at least 4.5:1, in the light and in the dark theme.
/// </summary>
public sealed class ThemeContrastTests
{
    private const double MinimumTextContrast = 4.5;

    private static readonly XNamespace Xaml = "http://schemas.microsoft.com/winfx/2006/xaml";

    /// <summary>Text token on background token, as the views and Controls.axaml combine them.</summary>
    public static TheoryData<string, string, string> Pairs()
    {
        (string Text, string Background)[] pairs =
        [
            ("TextPrimary", "Surface"), ("TextPrimary", "SurfaceAlt"),
            ("TextSecondary", "Surface"), ("TextSecondary", "SurfaceAlt"),
            ("SidebarText", "Sidebar"), ("SidebarText", "SidebarHover"), ("SidebarText", "SidebarSelected"),
            ("SidebarTextMuted", "Sidebar"), ("SidebarTextMuted", "SidebarHover"), ("SidebarTextMuted", "SidebarSelected"),
            ("OnAccent", "Accent"), ("OnAccent", "AccentHover"), ("OnAccent", "AccentPressed"),
            ("OnDanger", "Danger"), ("OnDanger", "DangerHover"), ("OnDanger", "DangerPressed"),
            ("AccentText", "Surface"), ("AccentText", "SurfaceAlt"),
            ("DangerText", "Surface"), ("DangerText", "SurfaceAlt"),
            ("WarningText", "Surface"), ("WarningText", "SurfaceAlt"),
            ("SuccessText", "Surface"), ("SuccessText", "SurfaceAlt"),
            ("TextPrimary", "InfoSurface"), ("TextPrimary", "WarningSurface"), ("TextPrimary", "DangerSurface"),
            ("TextPrimary", "AccentSubtle"),
            ("ChannelMic", "Surface"), ("ChannelSystem", "Surface"), ("ChannelOther", "Surface"),
        ];
        var data = new TheoryData<string, string, string>();
        foreach (var theme in new[] { "Light", "Dark" })
        {
            foreach (var (text, background) in pairs)
            {
                data.Add(theme, text, background);
            }
        }

        return data;
    }

    private static Dictionary<string, string> Palette(string theme) =>
        XDocument.Load(Path.Combine(ThemeTokensTests.DesktopFolder(), "Themes", "Tokens.axaml"))
            .Descendants()
            .Single(element => element.Name.LocalName == "ResourceDictionary" && (string?)element.Attribute(Xaml + "Key") == theme)
            .Elements()
            .ToDictionary(brush => (string)brush.Attribute(Xaml + "Key")!, brush => (string)brush.Attribute("Color")!);

    [Theory]
    [MemberData(nameof(Pairs))]
    public void Text_tokens_reach_the_minimum_contrast(string theme, string text, string background)
    {
        var palette = Palette(theme);

        var ratio = Contrast(palette[$"Brush.{text}"], palette[$"Brush.{background}"]);

        Assert.True(ratio >= MinimumTextContrast, $"{theme}: {text} on {background} is {ratio:0.00}:1");
    }

    [Fact]
    public void Both_themes_define_the_same_tokens()
    {
        Assert.Equal(Palette("Light").Keys.Order(), Palette("Dark").Keys.Order());
    }

    [Theory]
    [InlineData("#000000", "#FFFFFF", 21.0)]
    [InlineData("#FFFFFF", "#FFFFFF", 1.0)]
    [InlineData("#777777", "#FFFFFF", 4.48)]
    [InlineData("#FF2C1338", "#E57CD8", 6.53)]
    public void Contrast_follows_the_wcag_formula(string a, string b, double expected)
    {
        Assert.Equal(expected, Contrast(a, b), precision: 2);
    }

    internal static double Contrast(string a, string b)
    {
        var (lighter, darker) = (Luminance(a), Luminance(b)) is var (x, y) && x >= y ? (x, y) : (y, x);
        return (lighter + 0.05) / (darker + 0.05);
    }

    /// <summary>Relative luminance of <c>#RRGGBB</c> or <c>#AARRGGBB</c> (alpha ignored: tokens are opaque).</summary>
    private static double Luminance(string color)
    {
        var hex = color.TrimStart('#')[^6..];
        double Channel(int index)
        {
            var value = int.Parse(hex.AsSpan(index * 2, 2), NumberStyles.HexNumber, CultureInfo.InvariantCulture) / 255.0;
            return value <= 0.04045 ? value / 12.92 : Math.Pow((value + 0.055) / 1.055, 2.4);
        }

        return (0.2126 * Channel(0)) + (0.7152 * Channel(1)) + (0.0722 * Channel(2));
    }
}
