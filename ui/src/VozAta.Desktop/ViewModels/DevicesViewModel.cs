using System.Collections.ObjectModel;
using CommunityToolkit.Mvvm.ComponentModel;
using CommunityToolkit.Mvvm.Input;
using VozAta.Client;
using VozAta.Desktop.Services;

namespace VozAta.Desktop.ViewModels;

/// <summary>
/// Microphone and system-output (loopback) pickers from <c>GET /devices</c>. A remembered device is
/// restored by name (WASAPI ids change when devices are plugged in or out), then by id, else the
/// engine's default, else the first device. Choices the user makes are remembered.
/// </summary>
public sealed partial class DevicesViewModel(IEngineClient client, IUiPreferences preferences) : ObservableObject
{
    private bool _restoring;

    public ObservableCollection<AudioDevice> Inputs { get; } = [];

    public ObservableCollection<AudioDevice> Loopbacks { get; } = [];

    [ObservableProperty]
    public partial AudioDevice? SelectedMic { get; set; }

    [ObservableProperty]
    public partial AudioDevice? SelectedLoopback { get; set; }

    /// <summary>False while recording: the session keeps the devices it started with.</summary>
    [ObservableProperty]
    [NotifyCanExecuteChangedFor(nameof(RefreshCommand))]
    public partial bool IsEnabled { get; set; } = true;

    /// <summary>Ids for <c>POST /sessions</c>; null lets the engine use its default.</summary>
    public int? MicDeviceId => SelectedMic?.Id;

    public int? SystemDeviceId => SelectedLoopback?.Id;

    /// <summary>Load the device lists and restore the remembered selection; engine errors propagate.</summary>
    public async Task LoadAsync(CancellationToken cancellationToken = default)
    {
        var saved = preferences.Load();
        await ReloadAsync(saved.Mic, saved.Loopback, cancellationToken);
    }

    [RelayCommand(CanExecute = nameof(IsEnabled))]
    private Task RefreshAsync() => ReloadAsync(Choice(SelectedMic), Choice(SelectedLoopback), CancellationToken.None);

    partial void OnSelectedMicChanged(AudioDevice? value) => Remember();

    partial void OnSelectedLoopbackChanged(AudioDevice? value) => Remember();

    private async Task ReloadAsync(DeviceChoice? mic, DeviceChoice? loopback, CancellationToken cancellationToken)
    {
        var devices = await client.GetDevicesAsync(cancellationToken);
        _restoring = true;
        try
        {
            Replace(Inputs, devices.Inputs);
            Replace(Loopbacks, devices.Loopbacks);
            SelectedMic = Pick(Inputs, mic, devices.DefaultInputId);
            SelectedLoopback = Pick(Loopbacks, loopback, devices.DefaultLoopbackId);
        }
        finally
        {
            _restoring = false;
        }
    }

    private void Remember()
    {
        if (_restoring)
        {
            return;
        }

        preferences.Save(preferences.Load() with { Mic = Choice(SelectedMic), Loopback = Choice(SelectedLoopback) });
    }

    private static AudioDevice? Pick(ObservableCollection<AudioDevice> devices, DeviceChoice? remembered, int? defaultId) =>
        devices.FirstOrDefault(device => device.Name == remembered?.Name)
        ?? devices.FirstOrDefault(device => device.Id == remembered?.Id)
        ?? devices.FirstOrDefault(device => device.Id == defaultId)
        ?? (devices.Count > 0 ? devices[0] : null);

    private static DeviceChoice? Choice(AudioDevice? device) => device is null ? null : new DeviceChoice(device.Id, device.Name);

    private static void Replace(ObservableCollection<AudioDevice> target, IEnumerable<AudioDevice> devices)
    {
        target.Clear();
        foreach (var device in devices)
        {
            target.Add(device);
        }
    }
}
