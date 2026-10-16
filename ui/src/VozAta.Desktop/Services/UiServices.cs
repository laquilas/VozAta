using System.Diagnostics.CodeAnalysis;
using Avalonia.Threading;

namespace VozAta.Desktop.Services;

/// <summary>Runs work on the UI thread (engine events arrive on background threads).</summary>
public interface IUiDispatcher
{
    void Post(Action action);
}

[ExcludeFromCodeCoverage(Justification = "Avalonia's dispatcher; ViewModel tests use a fake.")]
public sealed class AvaloniaUiDispatcher : IUiDispatcher
{
    public void Post(Action action) => Dispatcher.UIThread.Post(action);
}

/// <summary>Modal questions to the user (implemented with Avalonia windows).</summary>
public interface IDialogService
{
    Task<bool> ConfirmAsync(string title, string message, string confirm, string cancel);
}
