using CommunityToolkit.Mvvm.ComponentModel;
using CommunityToolkit.Mvvm.Input;
using VozAta.Client;
using VozAta.Desktop.Services;

namespace VozAta.Desktop.ViewModels;

/// <summary>
/// Config → Storage (phase 38), from <c>GET /health</c> <c>storage</c>: backend, database path and
/// size, audio cache size with "Clear cache", and the OneDrive warning (phase 31).
/// </summary>
public sealed partial class StorageViewModel(
    IEngineClient client, IShellService shell, IDialogService dialogs, ILocalizationService localization) : ObservableObject
{
    private StorageStatus? _status;

    [ObservableProperty]
    public partial string BackendText { get; private set; } = "";

    [ObservableProperty]
    [NotifyPropertyChangedFor(nameof(HasDatabase))]
    [NotifyCanExecuteChangedFor(nameof(OpenFolderCommand))]
    public partial string? DatabasePath { get; private set; }

    public bool HasDatabase => DatabasePath is not null;

    [ObservableProperty]
    public partial string DatabaseSizeText { get; private set; } = "";

    [ObservableProperty]
    public partial string CacheSizeText { get; private set; } = "";

    [ObservableProperty]
    [NotifyCanExecuteChangedFor(nameof(ClearCacheCommand))]
    public partial long CacheBytes { get; private set; }

    /// <summary>The engine's localized OneDrive warning (null: none).</summary>
    [ObservableProperty]
    public partial string? Warning { get; private set; }

    [ObservableProperty]
    public partial string? Message { get; private set; }

    [ObservableProperty]
    public partial string? Error { get; private set; }

    [ObservableProperty]
    [NotifyCanExecuteChangedFor(nameof(ClearCacheCommand), nameof(RefreshCommand))]
    public partial bool IsBusy { get; private set; }

    public async Task LoadAsync(CancellationToken cancellationToken = default)
    {
        try
        {
            _status = (await client.GetHealthAsync(cancellationToken)).Storage;
            Error = null;
        }
        catch (Exception error) when (error is EngineApiException or EngineUnavailableException)
        {
            Error = ErrorText(error);
        }

        RefreshTexts();
    }

    public void RefreshTexts()
    {
        if (_status is not { } status)
        {
            return;
        }

        BackendText = localization[status.Backend == "sqlite" ? "StorageBackendSqlite" : "StorageBackendFiles"];
        DatabasePath = status.Database;
        DatabaseSizeText = status.SizeBytes is { } size ? ByteSize.Format(size, localization) : localization["StorageNoDatabase"];
        CacheBytes = status.AudioCacheBytes;
        CacheSizeText = ByteSize.Format(status.AudioCacheBytes, localization);
        Warning = status.Warning;
    }

    [RelayCommand(CanExecute = nameof(HasDatabase))]
    private void OpenFolder()
    {
        if (Path.GetDirectoryName(DatabasePath) is { Length: > 0 } folder)
        {
            shell.Open(folder);
        }
    }

    private bool CanClear() => CacheBytes > 0 && !IsBusy;

    [RelayCommand(CanExecute = nameof(CanClear))]
    private async Task ClearCacheAsync()
    {
        if (!await dialogs.ConfirmAsync(
                localization["StorageClearCacheTitle"], localization["StorageClearCacheMessage"],
                localization["StorageClearCache"], localization["StorageKeepCache"]))
        {
            return;
        }

        IsBusy = true;
        Message = Error = null;
        try
        {
            var cleared = await client.ClearAudioCacheAsync();
            Message = localization.Format("StorageCacheCleared", ByteSize.Format(cleared.FreedBytes, localization));
            await LoadAsync();
        }
        catch (Exception error) when (error is EngineApiException or EngineUnavailableException)
        {
            Error = ErrorText(error);
        }
        finally
        {
            IsBusy = false;
        }
    }

    private bool CanRefresh() => !IsBusy;

    [RelayCommand(CanExecute = nameof(CanRefresh))]
    private Task RefreshAsync() => LoadAsync();

    private string ErrorText(Exception error) =>
        error is EngineUnavailableException ? localization["EngineUnavailable"] : error.Message;
}

/// <summary>Byte counts as "12.3 MB" in the current language.</summary>
public static class ByteSize
{
    public static string Format(long bytes, ILocalizationService localization) => bytes switch
    {
        < 1024 => localization.Format("SizeBytes", bytes),
        < 1024 * 1024 => localization.Format("SizeKilobytes", bytes / 1024.0),
        < 1024L * 1024 * 1024 => localization.Format("SizeMegabytes", bytes / (1024.0 * 1024)),
        _ => localization.Format("SizeGigabytes", bytes / (1024.0 * 1024 * 1024)),
    };
}
