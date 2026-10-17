using System.Runtime.CompilerServices;
using System.Text.RegularExpressions;
using System.Xml.Linq;

namespace VozAta.Desktop.Tests;

/// <summary>
/// Views take their look from the design system (phase 34): colors, font sizes and fonts come from
/// <c>Themes/Tokens.axaml</c> and <c>Themes/Controls.axaml</c>, glyph buttons use <c>Themes/Icons.axaml</c>.
/// </summary>
public sealed partial class ThemeTokensTests
{
    private static readonly string[] ColorProperties = ["Foreground", "Background", "Fill", "Stroke", "BorderBrush"];

    internal static string DesktopFolder([CallerFilePath] string here = "") =>
        Path.GetFullPath(Path.Combine(Path.GetDirectoryName(here)!, "../../src/VozAta.Desktop"));

    private static readonly string[] TokenFiles = ["Tokens.axaml", "Icons.axaml"];

    private static List<string> ViewFiles() =>
        Directory.GetFiles(Path.Combine(DesktopFolder(), "Views"), "*.axaml").Order().Select(file => Path.GetFileName(file)).ToList();

    public static TheoryData<string> Views() => new(ViewFiles());

    private static IEnumerable<XAttribute> Attributes(string view) =>
        XDocument.Load(Path.Combine(DesktopFolder(), "Views", view)).Descendants().SelectMany(element => element.Attributes());

    private static IEnumerable<XElement> Setters(string view) =>
        XDocument.Load(Path.Combine(DesktopFolder(), "Views", view)).Descendants().Where(element => element.Name.LocalName == "Setter");

    [GeneratedRegex("#[0-9A-Fa-f]{3,8}\\b")]
    private static partial Regex HexColor();

    [Fact]
    public void Every_view_is_checked()
    {
        Assert.Contains("MainWindow.axaml", ViewFiles());
        Assert.True(ViewFiles().Count >= 6);
    }

    [Theory]
    [MemberData(nameof(Views))]
    public void Views_hold_no_hex_color_literal(string view)
    {
        var text = File.ReadAllText(Path.Combine(DesktopFolder(), "Views", view));

        Assert.Empty(HexColor().Matches(text).Select(match => match.Value));
    }

    [Theory]
    [MemberData(nameof(Views))]
    public void Colors_come_from_tokens_or_bindings(string view)
    {
        var literal = Attributes(view)
            .Where(attribute => ColorProperties.Contains(attribute.Name.LocalName))
            .Where(attribute => !attribute.Value.StartsWith('{') && attribute.Value != "Transparent")
            .Select(attribute => $"{attribute.Parent!.Name.LocalName}.{attribute.Name.LocalName}={attribute.Value}");
        var setters = Setters(view)
            .Where(setter => ColorProperties.Contains((string?)setter.Attribute("Property")))
            .Where(setter => !((string?)setter.Attribute("Value") ?? "{").StartsWith('{'))
            .Select(setter => $"Setter {(string?)setter.Attribute("Property")}");

        Assert.Empty(literal.Concat(setters));
    }

    [Theory]
    [MemberData(nameof(Views))]
    public void Font_sizes_and_families_come_from_the_type_scale(string view)
    {
        var literal = Attributes(view)
            .Where(attribute => attribute.Name.LocalName is "FontSize" or "FontFamily")
            .Where(attribute => !attribute.Value.StartsWith('{'))
            .Select(attribute => $"{attribute.Parent!.Name.LocalName}.{attribute.Name.LocalName}={attribute.Value}");
        var setters = Setters(view)
            .Where(setter => (string?)setter.Attribute("Property") is "FontSize" or "FontFamily")
            .Where(setter => !((string?)setter.Attribute("Value") ?? "{").StartsWith('{'))
            .Select(setter => $"Setter {(string?)setter.Attribute("Property")}");

        Assert.Empty(literal.Concat(setters));
    }

    [Theory]
    [MemberData(nameof(Views))]
    public void Buttons_use_icons_instead_of_glyphs(string view)
    {
        var glyphs = Attributes(view)
            .Where(attribute => attribute.Name.LocalName == "Content" && !attribute.Value.StartsWith('{'))
            .Where(attribute => attribute.Value.Length <= 2 && !attribute.Value.Any(char.IsLetterOrDigit))
            .Select(attribute => attribute.Value);

        Assert.Empty(glyphs);
    }

    [Fact]
    public void Every_resource_a_view_uses_is_defined()
    {
        var themes = Path.Combine(DesktopFolder(), "Themes");
        var defined = TokenFiles
            .SelectMany(file => XDocument.Load(Path.Combine(themes, file)).Descendants())
            .Select(element => (string?)element.Attribute(XName.Get("Key", "http://schemas.microsoft.com/winfx/2006/xaml")))
            .OfType<string>()
            .ToHashSet();
        var used = Directory.GetFiles(Path.Combine(DesktopFolder(), "Views"), "*.axaml")
            .Append(Path.Combine(themes, "Controls.axaml"))
            .SelectMany(file => ResourceReference().Matches(File.ReadAllText(file)).Select(match => match.Groups[1].Value))
            .Where(key => key.Contains('.'))
            .ToHashSet();

        Assert.NotEmpty(used);
        Assert.Empty(used.Except(defined));
    }

    [GeneratedRegex("\\{(?:Dynamic|Static)Resource ([\\w.]+)\\}")]
    private static partial Regex ResourceReference();
}
