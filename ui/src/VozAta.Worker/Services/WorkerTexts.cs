using System.Globalization;
using System.Resources;

namespace VozAta.Worker.Services;

/// <summary>The app's texts (en, pt-BR, es), in the Windows display language.</summary>
public interface IWorkerTexts
{
    string this[string key] { get; }

    string Format(string key, params object?[] values);
}

public sealed class WorkerTexts(CultureInfo? culture = null) : IWorkerTexts
{
    private static readonly ResourceManager Resources =
        new("VozAta.Worker.Resources.WorkerStrings", typeof(WorkerTexts).Assembly);

    private readonly CultureInfo _culture = culture ?? CultureInfo.CurrentUICulture;

    public string this[string key] => Resources.GetString(key, _culture) ?? key;

    public string Format(string key, params object?[] values) =>
        string.Format(_culture, this[key], values);
}
