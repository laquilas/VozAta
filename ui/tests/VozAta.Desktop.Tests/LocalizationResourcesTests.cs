using System.Runtime.CompilerServices;
using System.Xml.Linq;
using VozAta.Desktop.Services;

namespace VozAta.Desktop.Tests;

public sealed class LocalizationResourcesTests
{
    private static string ResourcesFolder([CallerFilePath] string here = "") =>
        Path.GetFullPath(Path.Combine(Path.GetDirectoryName(here)!, "../../src/VozAta.Desktop/Resources"));

    private static HashSet<string> Keys(string file) =>
        XDocument.Load(Path.Combine(ResourcesFolder(), file))
            .Root!.Elements("data")
            .Select(data => (string)data.Attribute("name")!)
            .ToHashSet();

    [Theory]
    [InlineData("Strings.pt-BR.resx")]
    [InlineData("Strings.es.resx")]
    public void Every_language_has_exactly_the_english_keys(string file)
    {
        var english = Keys("Strings.resx");
        var other = Keys(file);

        Assert.Empty(english.Except(other));
        Assert.Empty(other.Except(english));
    }

    [Fact]
    public void Every_value_is_filled_in_every_language()
    {
        foreach (var file in new[] { "Strings.resx", "Strings.pt-BR.resx", "Strings.es.resx" })
        {
            var empty = XDocument.Load(Path.Combine(ResourcesFolder(), file))
                .Root!.Elements("data")
                .Where(data => string.IsNullOrWhiteSpace((string?)data.Element("value")))
                .Select(data => (string)data.Attribute("name")!);
            Assert.Empty(empty);
        }
    }

    [Fact]
    public void Strings_switch_language_at_runtime_and_notify_bindings()
    {
        var localization = new LocalizationService();
        var changed = new List<string?>();
        localization.PropertyChanged += (_, args) => changed.Add(args.PropertyName);

        Assert.Equal("Start recording", localization["Start"]);
        localization.SetLanguage("pt-BR");
        Assert.Equal("Iniciar gravação", localization["Start"]);
        localization.SetLanguage("es");

        Assert.Equal("Iniciar grabación", localization["Start"]);
        Assert.Equal("es", localization.Language);
        Assert.Contains("Item[]", changed);
        Assert.Contains("Language", changed);
    }

    [Fact]
    public void Unknown_languages_fall_back_to_english_and_unknown_keys_are_marked()
    {
        var localization = new LocalizationService();

        localization.SetLanguage("fr");

        Assert.Equal("en", localization.Language);
        Assert.Equal("[NoSuchKey]", localization["NoSuchKey"]);
    }

    [Fact]
    public void Format_uses_the_current_language()
    {
        var localization = new LocalizationService();
        localization.SetLanguage("pt-BR");

        Assert.Equal("Detectado: Português", localization.Format("DetectedLanguage", localization["LanguagePt"]));
    }
}
