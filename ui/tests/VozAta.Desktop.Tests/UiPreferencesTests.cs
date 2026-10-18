using VozAta.Desktop.Services;

namespace VozAta.Desktop.Tests;

public sealed class UiPreferencesTests : IDisposable
{
    private readonly string _folder = Path.Combine(Path.GetTempPath(), "vozata-tests", Guid.NewGuid().ToString("N"));

    private string FilePath => Path.Combine(_folder, "VozAta", "ui.json");

    public void Dispose()
    {
        if (Directory.Exists(_folder))
        {
            Directory.Delete(_folder, recursive: true);
        }
    }

    [Fact]
    public void A_missing_file_gives_empty_preferences()
    {
        var preferences = new JsonFileUiPreferences(FilePath);

        Assert.Equal(new UiPreferencesData(), preferences.Load());
    }

    [Fact]
    public void Saved_preferences_are_loaded_back_and_the_folder_is_created()
    {
        var saved = new UiPreferencesData(
            new DeviceChoice(3, "Headset Mic (USB)"), new DeviceChoice(7, "Speakers [Loopback]"), 1200, 800);

        new JsonFileUiPreferences(FilePath).Save(saved);

        Assert.Equal(saved, new JsonFileUiPreferences(FilePath).Load());
        Assert.Contains("\"mic\"", File.ReadAllText(FilePath));
    }

    [Fact]
    public void The_theme_follows_the_system_until_one_is_chosen()
    {
        Assert.Equal("system", new UiPreferencesData().Theme);
    }

    [Fact]
    public void The_theme_is_saved_and_restored()
    {
        new JsonFileUiPreferences(FilePath).Save(new UiPreferencesData(Theme: "dark"));

        Assert.Equal("dark", new JsonFileUiPreferences(FilePath).Load().Theme);
        Assert.Contains("\"theme\"", File.ReadAllText(FilePath));
    }

    [Fact]
    public void A_file_saved_before_the_theme_existed_follows_the_system()
    {
        Directory.CreateDirectory(Path.GetDirectoryName(FilePath)!);
        File.WriteAllText(FilePath, """{"minimize_to_tray": true}""");

        var loaded = new JsonFileUiPreferences(FilePath).Load();

        Assert.True(loaded.MinimizeToTray);
        Assert.Equal("system", loaded.Theme);
    }

    [Theory]
    [InlineData("not json")]
    [InlineData("[1, 2]")]
    [InlineData("")]
    public void A_corrupt_file_gives_empty_preferences(string content)
    {
        Directory.CreateDirectory(Path.GetDirectoryName(FilePath)!);
        File.WriteAllText(FilePath, content);

        Assert.Equal(new UiPreferencesData(), new JsonFileUiPreferences(FilePath).Load());
    }

    [Fact]
    public void Saving_to_an_unwritable_place_is_ignored()
    {
        Directory.CreateDirectory(_folder);
        var blocked = Path.Combine(_folder, "file-not-folder");
        File.WriteAllText(blocked, "x");

        new JsonFileUiPreferences(Path.Combine(blocked, "ui.json")).Save(new UiPreferencesData(WindowWidth: 900));

        Assert.Equal("x", File.ReadAllText(blocked));
    }

    [Fact]
    public void The_default_location_is_under_the_roaming_app_data_folder()
    {
        var path = JsonFileUiPreferences.DefaultPath();

        Assert.StartsWith(Environment.GetFolderPath(Environment.SpecialFolder.ApplicationData), path);
        Assert.EndsWith(Path.Combine("VozAta", "ui.json"), path);
    }
}
