using VozAta.Client;

namespace VozAta.Desktop.Tests.Fakes;

/// <summary>Voice commands (phase 50): a saved list and the defaults, saved back trimmed.</summary>
internal sealed partial class FakeEngineClient
{
    public List<VoiceCommand> VoiceCommandDefaults { get; } =
    [
        new("make the minutes", "minutes", null),
        new("what was decided", "ask", "What was decided so far?"),
    ];

    /// <summary>The saved list; null = none saved (the defaults are used).</summary>
    public List<VoiceCommand>? SavedVoiceCommands { get; set; }

    public Exception? VoiceCommandsError { get; set; }

    public Task<VoiceCommandsView> GetVoiceCommandsAsync(CancellationToken cancellationToken = default) =>
        VoiceCommandsError is null
            ? Task.FromResult(new VoiceCommandsView([.. SavedVoiceCommands ?? VoiceCommandDefaults], [.. VoiceCommandDefaults]))
            : Task.FromException<VoiceCommandsView>(VoiceCommandsError);

    public Task<VoiceCommandsView> UpdateVoiceCommandsAsync(
        IReadOnlyList<VoiceCommand> commands, CancellationToken cancellationToken = default)
    {
        Calls.Add("put voice-commands");
        if (VoiceCommandsError is not null)
        {
            return Task.FromException<VoiceCommandsView>(VoiceCommandsError);
        }

        SavedVoiceCommands = [.. commands.Select(command => command with { Phrase = command.Phrase.Trim() })];
        return Task.FromResult(new VoiceCommandsView([.. SavedVoiceCommands], [.. VoiceCommandDefaults]));
    }
}
