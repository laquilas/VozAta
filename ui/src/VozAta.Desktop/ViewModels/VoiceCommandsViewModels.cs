using System.Collections.ObjectModel;
using CommunityToolkit.Mvvm.ComponentModel;
using CommunityToolkit.Mvvm.Input;
using VozAta.Client;
using VozAta.Desktop.Services;

namespace VozAta.Desktop.ViewModels;

/// <summary>One editable voice command of the Config page (phase 50).</summary>
public sealed partial class VoiceCommandRow : ObservableObject
{
    public VoiceCommandRow(VoiceCommand command, IReadOnlyList<ChoiceOption> actions)
    {
        Actions = actions;
        Phrase = command.Phrase;
        Action = actions.FirstOrDefault(option => option.Value == command.Action) ?? actions[0];
        Question = command.Question ?? "";
    }

    /// <summary>"Minutes so far" or "Ask".</summary>
    public IReadOnlyList<ChoiceOption> Actions { get; }

    [ObservableProperty]
    public partial string Phrase { get; set; }

    [ObservableProperty]
    [NotifyPropertyChangedFor(nameof(IsAsk))]
    public partial ChoiceOption Action { get; set; }

    [ObservableProperty]
    public partial string Question { get; set; }

    /// <summary>The question box shows for an "ask" command only.</summary>
    public bool IsAsk => Action.Value == "ask";

    public VoiceCommand ToCommand() => new(Phrase.Trim(), Action.Value, IsAsk ? Question.Trim() : null);
}

/// <summary>
/// The Voice commands group of the Config page (phase 50): the phrases said after the wake word
/// and what each does. Saved as a whole with <c>PUT /voice-commands</c>; the defaults of the app
/// language can be put back.
/// </summary>
public sealed partial class VoiceCommandsViewModel(IEngineClient client, ILocalizationService localization)
    : ObservableObject
{
    private IReadOnlyList<VoiceCommand> _defaults = [];

    public IReadOnlyList<ChoiceOption> Actions { get; } = Options(localization);

    public ObservableCollection<VoiceCommandRow> Rows { get; } = [];

    [ObservableProperty]
    [NotifyCanExecuteChangedFor(nameof(SaveCommand))]
    public partial bool IsBusy { get; private set; }

    [ObservableProperty]
    public partial string? Message { get; private set; }

    [ObservableProperty]
    public partial string? Error { get; private set; }

    public async Task LoadAsync(CancellationToken cancellationToken = default)
    {
        Error = null;
        try
        {
            var view = await client.GetVoiceCommandsAsync(cancellationToken);
            Show(view);
        }
        catch (Exception error) when (error is EngineApiException or EngineUnavailableException)
        {
            Error = ErrorText(error);
        }
    }

    [RelayCommand]
    private void Add()
    {
        Rows.Add(new VoiceCommandRow(new VoiceCommand("", "ask", ""), Actions));
        Message = null;
    }

    [RelayCommand]
    private void Remove(VoiceCommandRow row)
    {
        Rows.Remove(row);
        Message = null;
    }

    [RelayCommand]
    private void RestoreDefaults()
    {
        Fill(_defaults);
        Message = localization["VoiceCommandsDefaultsRestored"];
    }

    private bool CanSave() => !IsBusy;

    [RelayCommand(CanExecute = nameof(CanSave))]
    private async Task SaveAsync()
    {
        IsBusy = true;
        Message = Error = null;
        try
        {
            var saved = await client.UpdateVoiceCommandsAsync([.. Rows.Select(row => row.ToCommand())]);
            Show(saved);
            Message = localization["VoiceCommandsSaved"];
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

    private void Show(VoiceCommandsView view)
    {
        _defaults = view.Defaults;
        Fill(view.Commands);
    }

    private void Fill(IEnumerable<VoiceCommand> commands)
    {
        Rows.Clear();
        foreach (var command in commands)
        {
            Rows.Add(new VoiceCommandRow(command, Actions));
        }
    }

    private static List<ChoiceOption> Options(ILocalizationService localization)
    {
        List<ChoiceOption> options = [new("minutes", "VoiceActionMinutes"), new("ask", "VoiceActionAsk")];
        options.ForEach(option => option.Refresh(localization));
        return options;
    }

    private string ErrorText(Exception error) =>
        error is EngineUnavailableException ? localization["EngineUnavailable"] : error.Message;
}

/// <summary>
/// The recorder's answer to a question asked by voice (phase 50): opens when the command is heard,
/// streams the answer, then can be copied or closed.
/// </summary>
public sealed partial class VoiceAnswerViewModel(IShellService? shell, ILocalizationService localization, Action<string> notify)
    : ObservableObject
{
    private string? _answerId;

    [ObservableProperty]
    public partial string? Question { get; private set; }

    [ObservableProperty]
    public partial string Text { get; private set; } = "";

    [ObservableProperty]
    public partial bool IsOpen { get; private set; }

    [ObservableProperty]
    public partial bool IsAnswering { get; private set; }

    [ObservableProperty]
    public partial string? Error { get; private set; }

    public void Begin(string answerId, string? question)
    {
        _answerId = answerId;
        Question = question;
        Text = "";
        Error = null;
        IsAnswering = true;
        IsOpen = true;
    }

    public void OnChunk(AnswerChunkEvent chunk)
    {
        if (chunk.AnswerId == _answerId)
        {
            Text += chunk.Text;
        }
    }

    public void OnDone(AnswerDoneEvent done)
    {
        if (done.AnswerId != _answerId)
        {
            return;
        }

        IsAnswering = false;
        Error = done.Error;
    }

    [RelayCommand]
    private async Task CopyAsync()
    {
        if (shell is not null)
        {
            await shell.CopyTextAsync(string.IsNullOrEmpty(Question) ? Text : $"{Question}\n\n{Text}");
            notify(localization["Copied"]);
        }
    }

    [RelayCommand]
    private void Close() => IsOpen = false;

    /// <summary>The sidebar's "Resposta pronta" was clicked (phase 59): show the last answer again.</summary>
    public void Reopen() => IsOpen = _answerId is not null;
}
