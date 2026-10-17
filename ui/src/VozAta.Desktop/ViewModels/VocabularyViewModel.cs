using System.Collections.ObjectModel;
using CommunityToolkit.Mvvm.ComponentModel;
using CommunityToolkit.Mvvm.Input;
using VozAta.Client;
using VozAta.Desktop.Services;

namespace VozAta.Desktop.ViewModels;

/// <summary>
/// The glossary editor of the settings page (phase 19): add, remove or import terms. Every change
/// is saved at once with <c>PUT /vocabulary</c> and the list shows the terms as the engine kept them.
/// </summary>
public sealed partial class VocabularyViewModel(IEngineClient client, ILocalizationService localization) : ObservableObject
{
    private static readonly char[] Separators = [',', ';', '\r', '\n'];

    public ObservableCollection<string> Terms { get; } = [];

    public bool IsEmpty => Terms.Count == 0;

    [ObservableProperty]
    [NotifyCanExecuteChangedFor(nameof(AddCommand))]
    public partial string NewTerm { get; set; } = "";

    [ObservableProperty]
    [NotifyCanExecuteChangedFor(nameof(ImportCommand))]
    public partial string ImportText { get; set; } = "";

    [ObservableProperty]
    [NotifyCanExecuteChangedFor(nameof(AddCommand), nameof(ImportCommand), nameof(RemoveCommand))]
    public partial bool IsBusy { get; private set; }

    [ObservableProperty]
    public partial string? Message { get; private set; }

    [ObservableProperty]
    public partial string? Error { get; private set; }

    /// <summary>Terms typed as free text: split on commas, semicolons and line breaks, trimmed, no duplicates.</summary>
    public static IReadOnlyList<string> ParseTerms(string? text) =>
        [.. (text ?? "")
            .Split(Separators, StringSplitOptions.RemoveEmptyEntries | StringSplitOptions.TrimEntries)
            .DistinctBy(term => term.ToUpperInvariant())];

    public async Task LoadAsync(CancellationToken cancellationToken = default)
    {
        Error = null;
        try
        {
            Show(await client.GetVocabularyAsync(cancellationToken));
        }
        catch (Exception error) when (error is EngineApiException or EngineUnavailableException)
        {
            Error = ErrorText(error);
        }
    }

    private bool CanAdd() => !IsBusy && ParseTerms(NewTerm).Count > 0;

    [RelayCommand(CanExecute = nameof(CanAdd))]
    private async Task AddAsync()
    {
        if (await SaveAsync([.. Terms, .. ParseTerms(NewTerm)]))
        {
            NewTerm = "";
        }
    }

    private bool CanImport() => !IsBusy && ParseTerms(ImportText).Count > 0;

    [RelayCommand(CanExecute = nameof(CanImport))]
    private async Task ImportAsync()
    {
        if (await SaveAsync([.. Terms, .. ParseTerms(ImportText)]))
        {
            ImportText = "";
        }
    }

    private bool CanRemove(string? term) => !IsBusy && term is not null;

    [RelayCommand(CanExecute = nameof(CanRemove))]
    private async Task RemoveAsync(string? term)
    {
        await SaveAsync([.. Terms.Where(item => item != term)]);
    }

    private async Task<bool> SaveAsync(IReadOnlyList<string> terms)
    {
        IsBusy = true;
        Message = Error = null;
        try
        {
            Show(await client.UpdateVocabularyAsync(terms));
            Message = localization["VocabularySaved"];
            return true;
        }
        catch (Exception error) when (error is EngineApiException or EngineUnavailableException)
        {
            Error = ErrorText(error);
            return false;
        }
        finally
        {
            IsBusy = false;
        }
    }

    private void Show(IReadOnlyList<string> terms)
    {
        Terms.Clear();
        foreach (var term in terms)
        {
            Terms.Add(term);
        }

        OnPropertyChanged(nameof(IsEmpty));
    }

    private string ErrorText(Exception error) =>
        error is EngineUnavailableException ? localization["EngineUnavailable"] : error.Message;
}
