namespace VozAta.Worker.Services;

/// <summary>Where the worker program lives (<c>Worker</c> section of appsettings.json).</summary>
public sealed class WorkerOptions
{
    /// <summary>The packaged engine, next to this app once installed.</summary>
    public string ExecutablePath { get; set; } = "engine/vozata-engine.exe";

    /// <summary>Development: the repository's Python, which runs <c>-m vozata worker</c>.</summary>
    public string PythonPath { get; set; } = ".venv/Scripts/python.exe";

    /// <summary>The worker's own folder: its <c>.env</c> (token, id) and <c>worker.log</c>.</summary>
    public string WorkingDirectory { get; set; } = "%APPDATA%/VozAta/worker";
}

/// <summary>How to start the worker.</summary>
public sealed record WorkerCommand(string FileName, string Arguments, string WorkingDirectory)
{
    /// <summary>
    /// The packaged engine, else Python with the source engine. Relative paths are looked for in
    /// <paramref name="appDirectory"/> and each folder above it (the build output sits inside
    /// the repository in development). Null when neither exists.
    /// </summary>
    public static WorkerCommand? Resolve(WorkerOptions options, string appDirectory, Func<string, bool>? exists = null)
    {
        exists ??= File.Exists;
        var folder = Path.GetFullPath(Environment.ExpandEnvironmentVariables(options.WorkingDirectory));
        if (Find(options.ExecutablePath, appDirectory, exists) is { } engine)
        {
            return new WorkerCommand(engine, "worker", folder);
        }

        return Find(options.PythonPath, appDirectory, exists) is { } python
            ? new WorkerCommand(python, "-m vozata worker", folder)
            : null;
    }

    private static string? Find(string path, string appDirectory, Func<string, bool> exists)
    {
        if (Path.IsPathRooted(path))
        {
            return exists(path) ? path : null;
        }

        for (var root = new DirectoryInfo(appDirectory); root is not null; root = root.Parent)
        {
            var candidate = Path.GetFullPath(Path.Combine(root.FullName, path));
            if (exists(candidate))
            {
                return candidate;
            }
        }

        return null;
    }
}

/// <summary>The worker's ports, read from its <c>.env</c> (defaults 8766 / 8767).</summary>
public sealed record WorkerPorts(int Http, int Discovery)
{
    public static WorkerPorts Read(string envFile)
    {
        var values = new Dictionary<string, string>(StringComparer.Ordinal);
        if (File.Exists(envFile))
        {
            foreach (var line in File.ReadAllLines(envFile))
            {
                var at = line.IndexOf('=');
                if (at > 0 && !line.TrimStart().StartsWith('#'))
                {
                    values[line[..at].Trim()] = line[(at + 1)..].Trim();
                }
            }
        }

        return new WorkerPorts(Port(values, "WORKER_PORT", 8766), Port(values, "WORKER_DISCOVERY_PORT", 8767));
    }

    private static int Port(Dictionary<string, string> values, string key, int fallback) =>
        values.TryGetValue(key, out var text) && int.TryParse(text, out var port) && port is > 0 and < 65536
            ? port
            : fallback;
}
