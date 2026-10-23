using System.Collections.ObjectModel;
using CommunityToolkit.Mvvm.ComponentModel;
using CommunityToolkit.Mvvm.Input;
using VozAta.Worker.Services;

namespace VozAta.Worker.ViewModels;

/// <summary>A row of the Tasks card (phase 51): "Speaker identification", offered or why not.</summary>
public sealed record WorkerTaskRow(string Name, bool Offered, string Detail);

public enum WorkerState
{
    Stopped,
    Starting,
    Running,
    Failed,
}

/// <summary>
/// The window of VozAta Worker (phase 47): starts and stops the worker, shows how other PCs reach
/// it (addresses, the pairing code, the token) and what it runs (GPU, model), and sets it up to
/// start with Windows and to be reachable through the firewall.
/// </summary>
public sealed partial class WorkerAppViewModel : ObservableObject
{
    private readonly IWorkerProcess _process;
    private readonly IWorkerStatusClient _status;
    private readonly IStartupRegistry _startup;
    private readonly IFirewall _firewall;
    private readonly Func<WorkerPorts> _ports;

    public WorkerAppViewModel(
        IWorkerProcess process,
        IWorkerStatusClient status,
        IStartupRegistry startup,
        IFirewall firewall,
        IWorkerTexts texts,
        Func<WorkerPorts> ports)
    {
        _process = process;
        _status = status;
        _startup = startup;
        _firewall = firewall;
        _ports = ports;
        T = texts;
        _startWithWindows = startup.IsEnabled;
    }

    /// <summary>The texts, for the view: <c>{Binding T[Key]}</c>.</summary>
    public IWorkerTexts T { get; }

    /// <summary>One address per network of this PC, e.g. <c>http://192.168.0.20:8766</c>.</summary>
    public ObservableCollection<string> Addresses { get; } = [];

    /// <summary>What the worker offers to the other PCs, and why a task is missing (phase 51).</summary>
    public ObservableCollection<WorkerTaskRow> Tasks { get; } = [];

    [ObservableProperty]
    public partial bool HasTasks { get; private set; }

    [ObservableProperty]
    [NotifyPropertyChangedFor(nameof(StateText), nameof(StateTag), nameof(IsRunning), nameof(IsFailed))]
    [NotifyCanExecuteChangedFor(nameof(StartCommand), nameof(StopCommand))]
    public partial WorkerState State { get; private set; }

    /// <summary>What the state means for the other PCs (a sentence).</summary>
    public string StateText => T[$"WorkerState_{State}"];

    /// <summary>The state tag next to the name ("Running").</summary>
    public string StateTag => T[$"WorkerTag_{State}"];

    public bool IsRunning => State == WorkerState.Running;

    public bool IsFailed => State == WorkerState.Failed;

    [ObservableProperty]
    public partial string? Name { get; private set; }

    [ObservableProperty]
    public partial string? Version { get; private set; }

    [ObservableProperty]
    public partial string? Gpu { get; private set; }

    [ObservableProperty]
    public partial string? Model { get; private set; }

    [ObservableProperty]
    [NotifyPropertyChangedFor(nameof(HasPairingCode))]
    public partial string? PairingCode { get; private set; }

    public bool HasPairingCode => PairingCode is not null;

    /// <summary>"Valid for 4:32".</summary>
    [ObservableProperty]
    public partial string? CodeExpires { get; private set; }

    [ObservableProperty]
    public partial string? Token { get; private set; }

    [ObservableProperty]
    public partial string? Message { get; private set; }

    [ObservableProperty]
    public partial string? Error { get; private set; }

    private bool _startWithWindows;

    public bool StartWithWindows
    {
        get => _startWithWindows;
        set
        {
            if (SetProperty(ref _startWithWindows, value))
            {
                _startup.Apply(value);
            }
        }
    }

    private bool CanStart() => State is WorkerState.Stopped or WorkerState.Failed;

    [RelayCommand(CanExecute = nameof(CanStart))]
    private void Start()
    {
        Message = Error = null;
        if (!_process.Start())
        {
            State = WorkerState.Failed;
            Error = T["WorkerNotFound"];
            return;
        }

        State = WorkerState.Starting;
    }

    private bool CanStop() => State is WorkerState.Starting or WorkerState.Running;

    [RelayCommand(CanExecute = nameof(CanStop))]
    private void Stop()
    {
        _process.Terminate();
        State = WorkerState.Stopped;
        Message = Error = null;
        Clear();
    }

    [RelayCommand]
    private async Task AllowNetworkAsync()
    {
        var ports = _ports();
        Message = Error = null;
        if (await _firewall.AllowAsync(ports.Http, ports.Discovery))
        {
            Message = T.Format("WorkerFirewallDone", ports.Http, ports.Discovery);
        }
        else
        {
            Error = T["WorkerFirewallFailed"];
        }
    }

    /// <summary>Read the worker's status (every 2 s while it runs).</summary>
    public async Task RefreshAsync(CancellationToken cancellationToken = default)
    {
        if (State is WorkerState.Stopped or WorkerState.Failed)
        {
            return;
        }

        if (!_process.IsRunning)
        {
            State = WorkerState.Failed;
            Error = T.Format("WorkerExited", _process.LogPath);
            Clear();
            return;
        }

        var ports = _ports();
        if (await _status.GetAsync(ports.Http, cancellationToken) is not { } status)
        {
            return; // still loading, or busy for a moment
        }

        State = WorkerState.Running;
        Show(status);
    }

    /// <summary>When the app exits: the worker stops with it.</summary>
    public void Shutdown() => _process.Terminate();

    private void Show(LocalStatus status)
    {
        Name = status.Name;
        Version = status.Version;
        Gpu = status.Gpu.Available ? status.Gpu.Name : T["WorkerNoGpu"];
        Model = status.Models.Count > 0 ? string.Join(", ", status.Models) : T["WorkerNoModel"];
        PairingCode = status.PairingCode;
        CodeExpires = status.CodeExpiresIn is { } seconds
            ? T.Format("WorkerCodeExpires", $"{seconds / 60}:{seconds % 60:00}")
            : null;
        Token = status.Token;
        var urls = status.Addresses.Select(address => $"http://{address}:{status.Port}").ToList();
        if (!urls.SequenceEqual(Addresses))
        {
            Addresses.Clear();
            foreach (var url in urls)
            {
                Addresses.Add(url);
            }
        }

        var rows = (status.Tasks ?? []).Select(Row).ToList();
        if (!rows.SequenceEqual(Tasks))
        {
            Tasks.Clear();
            foreach (var row in rows)
            {
                Tasks.Add(row);
            }
        }

        HasTasks = Tasks.Count > 0;
    }

    private WorkerTaskRow Row(WorkerTaskStatus task)
    {
        var detail = (task.Available, task.Reason) switch
        {
            (true, _) => T["WorkerTaskOffered"],
            (false, "missing_hf_token") => T.Format("WorkerTaskNeedsToken", EnvFile()),
            (false, "missing_extra") => T["WorkerTaskNotInEdition"],
            _ => T["WorkerTaskNotOffered"],
        };
        return new WorkerTaskRow(T[$"WorkerTask_{task.Name}"], task.Available, detail);
    }

    /// <summary>The worker's <c>.env</c>, next to its log.</summary>
    private string EnvFile() => Path.Combine(Path.GetDirectoryName(_process.LogPath) ?? "", ".env");

    private void Clear()
    {
        Name = Version = Gpu = Model = PairingCode = CodeExpires = Token = null;
        Addresses.Clear();
        Tasks.Clear();
        HasTasks = false;
    }
}
