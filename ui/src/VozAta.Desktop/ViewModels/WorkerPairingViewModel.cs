using System.Collections.ObjectModel;
using CommunityToolkit.Mvvm.ComponentModel;
using CommunityToolkit.Mvvm.Input;
using VozAta.Client;
using VozAta.Desktop.Services;

namespace VozAta.Desktop.ViewModels;

/// <summary>A worker found on the network, with the code the user types to pair with it.</summary>
public sealed partial class FoundWorkerViewModel(FoundWorker worker, string detail, Func<FoundWorkerViewModel, Task> pair)
    : ObservableObject
{
    public FoundWorker Worker { get; } = worker;

    public string Name => Worker.Name;

    /// <summary>Address, version and GPU, e.g. <c>http://192.168.0.20:8766 · 0.9.0 · RTX 4070</c>.</summary>
    public string Detail { get; } = detail;

    [ObservableProperty]
    [NotifyCanExecuteChangedFor(nameof(PairCommand))]
    public partial string Code { get; set; } = "";

    [ObservableProperty]
    [NotifyCanExecuteChangedFor(nameof(PairCommand))]
    public partial bool IsPairing { get; set; }

    private bool CanPair() => !IsPairing && !string.IsNullOrWhiteSpace(Code);

    [RelayCommand(CanExecute = nameof(CanPair))]
    private Task PairAsync() => pair(this);
}

/// <summary>
/// The Config page's Worker group (phase 47): look for VozAta workers on the local network and
/// pair with one by the code VozAta Worker shows on the GPU PC. The engine saves the address,
/// token and id; <see cref="Paired"/> lets the page show them.
/// </summary>
public sealed partial class WorkerPairingViewModel(IEngineClient client, ILocalizationService localization)
    : ObservableObject
{
    public ObservableCollection<FoundWorkerViewModel> Workers { get; } = [];

    [ObservableProperty]
    [NotifyCanExecuteChangedFor(nameof(FindCommand))]
    public partial bool IsSearching { get; private set; }

    [ObservableProperty]
    public partial string? Message { get; private set; }

    [ObservableProperty]
    public partial string? Error { get; private set; }

    /// <summary>Raised after a pairing the engine saved.</summary>
    public Func<PairedWorker, Task>? Paired { get; set; }

    private bool CanFind() => !IsSearching;

    [RelayCommand(CanExecute = nameof(CanFind))]
    private async Task FindAsync()
    {
        IsSearching = true;
        Message = localization["WorkerSearching"];
        Error = null;
        Workers.Clear();
        try
        {
            var found = await client.DiscoverWorkersAsync();
            foreach (var worker in found.Workers)
            {
                Workers.Add(new FoundWorkerViewModel(worker, Detail(worker), PairAsync));
            }

            Message = Workers.Count == 0 ? localization["WorkerNoneFound"] : localization["WorkerTypeCode"];
        }
        catch (Exception error) when (error is EngineApiException or EngineUnavailableException)
        {
            Message = null;
            Error = ErrorText(error);
        }
        finally
        {
            IsSearching = false;
        }
    }

    private async Task PairAsync(FoundWorkerViewModel item)
    {
        item.IsPairing = true;
        Message = Error = null;
        try
        {
            var paired = await client.PairWorkerAsync(item.Worker.Url, item.Code.Trim());
            item.Code = "";
            Message = localization.Format("WorkerPaired", paired.Name);
            if (Paired is not null)
            {
                await Paired(paired);
            }
        }
        catch (Exception error) when (error is EngineApiException or EngineUnavailableException)
        {
            Error = ErrorText(error);
        }
        finally
        {
            item.IsPairing = false;
        }
    }

    private string Detail(FoundWorker worker) =>
        $"{worker.Url} · VozAta {worker.Version} · {worker.Gpu ?? localization["WorkerNoGpu"]}";

    private string ErrorText(Exception error) =>
        error is EngineUnavailableException ? localization["EngineUnavailable"] : error.Message;
}
