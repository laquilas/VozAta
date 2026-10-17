namespace VozAta.Client;

// Ask the meeting (api-contract rows tagged 24): POST /ask, then answer_chunk / answer_done events.

/// <summary><c>POST /ask</c> body; a null <see cref="SessionId"/> asks about every session.</summary>
public sealed record AskRequest(string Question, string? SessionId = null);

/// <summary><c>POST /ask</c> answer: the id the streamed events carry.</summary>
public sealed record AskAccepted(string AnswerId);

/// <summary>A transcript segment an answer cites (<c>[session_id@hh:mm:ss]</c> in the text).</summary>
public sealed record Citation(string SessionId, string SegmentId, double Start);

/// <summary>Streamed answer text, in order; <c>SessionId</c> is the question's scope.</summary>
public sealed record AnswerChunkEvent(string? SessionId, string AnswerId, string Text) : EngineEvent(SessionId);

/// <summary>The answer is complete; <see cref="Error"/> is a localized message when it failed.</summary>
public sealed record AnswerDoneEvent(
    string? SessionId, string AnswerId, IReadOnlyList<Citation> Citations, string? Error) : EngineEvent(SessionId);
