using System.Text.Json;

namespace VozAta.Client;

/// <summary>JSON settings shared by HTTP and WebSocket: the engine speaks snake_case.</summary>
public static class EngineJson
{
    public static JsonSerializerOptions Options { get; } = new(JsonSerializerDefaults.Web)
    {
        PropertyNamingPolicy = JsonNamingPolicy.SnakeCaseLower,
        DictionaryKeyPolicy = null, // setting keys such as "MIX_MODE" stay as they are
    };
}
