using VozAta.Client;
using VozAta.Desktop.Services;
using VozAta.Desktop.Tests.Fakes;
using VozAta.Desktop.ViewModels;

namespace VozAta.Desktop.Tests;

public sealed class DevicesViewModelTests
{
    private static readonly AudioDevice Laptop = new(1, "Microphone Array (Intel)", 48000, 2);
    private static readonly AudioDevice Usb = new(4, "JBL Quantum Stream", 48000, 1);
    private static readonly AudioDevice Speakers = new(7, "Speakers [Loopback]", 48000, 2);
    private static readonly AudioDevice Headset = new(9, "Headset [Loopback]", 48000, 2);

    private readonly FakeEngineClient _client = new()
    {
        Devices = new DeviceList([Laptop, Usb], [Speakers, Headset], DefaultInputId: 4, DefaultLoopbackId: 7),
    };

    private readonly FakePreferences _preferences = new();

    private DevicesViewModel Create() => new(_client, _preferences);

    [Fact]
    public async Task Without_preferences_the_engine_defaults_are_selected()
    {
        var devices = Create();

        await devices.LoadAsync();

        Assert.Equal([Laptop, Usb], devices.Inputs);
        Assert.Equal([Speakers, Headset], devices.Loopbacks);
        Assert.Equal((Usb, Speakers), (devices.SelectedMic, devices.SelectedLoopback));
        Assert.Equal((4, 7), (devices.MicDeviceId, devices.SystemDeviceId));
        Assert.Equal(0, _preferences.Saves);  // restoring is not a user choice
    }

    [Fact]
    public async Task A_remembered_device_is_restored_by_name_even_when_its_id_changed()
    {
        _preferences.Data = new UiPreferencesData(new DeviceChoice(2, "Microphone Array (Intel)"), new DeviceChoice(9, "Headset [Loopback]"));
        var devices = Create();

        await devices.LoadAsync();

        Assert.Equal((Laptop, Headset), (devices.SelectedMic, devices.SelectedLoopback));
    }

    [Fact]
    public async Task A_renamed_device_is_found_by_id_and_a_missing_one_falls_back_to_the_default()
    {
        _preferences.Data = new UiPreferencesData(new DeviceChoice(1, "Old mic name"), new DeviceChoice(42, "Unplugged headset"));
        var devices = Create();

        await devices.LoadAsync();

        Assert.Equal((Laptop, Speakers), (devices.SelectedMic, devices.SelectedLoopback));
    }

    [Fact]
    public async Task Without_an_engine_default_the_first_device_is_used_and_an_empty_list_selects_nothing()
    {
        _client.Devices = new DeviceList([Laptop, Usb], [], null, null);
        var devices = Create();

        await devices.LoadAsync();

        Assert.Equal(Laptop, devices.SelectedMic);
        Assert.Null(devices.SelectedLoopback);
        Assert.Null(devices.SystemDeviceId);  // the engine picks its default
    }

    [Fact]
    public async Task Choosing_a_device_remembers_it_and_keeps_the_other_preferences()
    {
        _preferences.Data = new UiPreferencesData(WindowWidth: 1100, WindowHeight: 700);
        var devices = Create();
        await devices.LoadAsync();

        devices.SelectedMic = Laptop;
        devices.SelectedLoopback = Headset;

        Assert.Equal(
            new UiPreferencesData(new DeviceChoice(1, "Microphone Array (Intel)"), new DeviceChoice(9, "Headset [Loopback]"), 1100, 700),
            _preferences.Data);
    }

    [Fact]
    public async Task Refresh_reloads_the_lists_and_keeps_the_current_choice()
    {
        var devices = Create();
        await devices.LoadAsync();
        devices.SelectedMic = Laptop;
        var bluetooth = new AudioDevice(11, "Bluetooth Headset", 16000, 1);
        _client.Devices = _client.Devices with { Inputs = [bluetooth, new AudioDevice(3, "Microphone Array (Intel)", 48000, 2)] };

        await devices.RefreshCommand.ExecuteAsync(null);

        Assert.Equal(2, devices.Inputs.Count);
        Assert.Equal(3, devices.MicDeviceId);
    }

    [Fact]
    public async Task Devices_cannot_change_or_refresh_while_disabled()
    {
        var devices = Create();
        await devices.LoadAsync();

        devices.IsEnabled = false;

        Assert.False(devices.RefreshCommand.CanExecute(null));
        devices.IsEnabled = true;
        Assert.True(devices.RefreshCommand.CanExecute(null));
    }

    [Fact]
    public async Task Load_errors_reach_the_caller()
    {
        _client.DevicesError = new EngineUnavailableException("refused", new HttpRequestException());

        await Assert.ThrowsAsync<EngineUnavailableException>(() => Create().LoadAsync());
    }

    private sealed class FakePreferences : IUiPreferences
    {
        public UiPreferencesData Data { get; set; } = new();

        public int Saves { get; private set; }

        public UiPreferencesData Load() => Data;

        public void Save(UiPreferencesData preferences)
        {
            Data = preferences;
            Saves++;
        }
    }
}
