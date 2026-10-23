namespace VozAta.Client;

// Voice commands while recording (api-contract rows tagged 50).

/// <summary>A phrase said after the wake word: <c>minutes</c> (minutes so far) or <c>ask</c> (<see cref="Question"/>).</summary>
public sealed record VoiceCommand(string Phrase, string Action, string? Question);

/// <summary><c>GET|PUT /voice-commands</c>: the saved list and the defaults of the app language.</summary>
public sealed record VoiceCommandsView(IReadOnlyList<VoiceCommand> Commands, IReadOnlyList<VoiceCommand> Defaults);

/// <summary>A voice command was heard (<c>voice_command</c>); an <c>ask</c> streams its answer as <see cref="AnswerId"/>.</summary>
public sealed record VoiceCommandEvent(string? SessionId, string Action, string Phrase, string? Question, string? AnswerId)
    : EngineEvent(SessionId);
