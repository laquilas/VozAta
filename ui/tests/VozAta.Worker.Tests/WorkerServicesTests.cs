using System.Globalization;
using System.Net;
using System.Xml.Linq;
using VozAta.Worker.Services;
using VozAta.Worker.ViewModels;

namespace VozAta.Worker.Tests;

public sealed class WorkerServicesTests
{
    private static readonly string App = Path.Combine(Path.GetTempPath(), "repo", "ui", "bin");

    [Fact]
    public void The_packaged_engine_is_preferred()
    {
        var engine = Path.GetFullPath(Path.Combine(App, "engine/vozata-engine.exe"));
        var python = Path.GetFullPath(Path.Combine(App, "..", "..", ".venv/Scripts/python.exe"));
        var options = new WorkerOptions { WorkingDirectory = Path.Combine(Path.GetTempPath(), "w") };

        var command = WorkerCommand.Resolve(options, App, path => path == engine || path == python);

        Assert.Equal(new WorkerCommand(engine, "worker", Path.Combine(Path.GetTempPath(), "w")), command);
    }

    [Fact]
    public void Development_runs_the_source_engine_with_the_python_above_the_app()
    {
        var python = Path.GetFullPath(Path.Combine(App, "..", "..", ".venv/Scripts/python.exe"));

        var command = WorkerCommand.Resolve(new WorkerOptions(), App, path => path == python);

        Assert.Equal((python, "-m vozata worker"), (command!.FileName, command.Arguments));
        Assert.DoesNotContain("%APPDATA%", command.WorkingDirectory, StringComparison.Ordinal);
    }

    [Fact]
    public void A_rooted_path_is_used_as_it_is_and_nothing_found_is_null()
    {
        var rooted = Path.Combine(Path.GetTempPath(), "custom", "vozata-engine.exe");
        var options = new WorkerOptions { ExecutablePath = rooted };

        Assert.Equal(rooted, WorkerCommand.Resolve(options, App, path => path == rooted)!.FileName);
        Assert.Null(WorkerCommand.Resolve(options, App, _ => false));
    }

    [Fact]
    public void The_ports_are_read_from_the_worker_env_file()
    {
        var file = Path.Combine(Path.GetTempPath(), $"worker-{Guid.NewGuid():N}.env");
        File.WriteAllLines(file, ["# WORKER_PORT=1", "WORKER_TOKEN=abc=def", " WORKER_PORT = 9000 ", "WORKER_DISCOVERY_PORT=99999"]);
        try
        {
            Assert.Equal(new WorkerPorts(9000, 8767), WorkerPorts.Read(file));
        }
        finally
        {
            File.Delete(file);
        }
    }

    [Fact]
    public void Without_an_env_file_the_ports_are_the_defaults() =>
        Assert.Equal(new WorkerPorts(8766, 8767), WorkerPorts.Read(Path.Combine(Path.GetTempPath(), "missing", ".env")));

    [Fact]
    public async Task The_local_status_is_read_from_this_pc()
    {
        var handler = new Handler(_ => new HttpResponseMessage(HttpStatusCode.OK)
        {
            Content = new StringContent("""
                {"version": "0.9.0", "id": "4f1c", "name": "GPU-PC", "port": 8766,
                 "addresses": ["192.168.0.20"], "token": "t0k", "pairing_code": "123456",
                 "code_expires_in": 300, "gpu": {"available": true, "name": "RTX 4070", "vram_total_mb": 12282},
                 "models": []}
                """),
        });

        var status = await new WorkerStatusClient(new HttpClient(handler)).GetAsync(8766);

        Assert.Equal("http://127.0.0.1:8766/local/status", handler.Uri?.ToString());
        Assert.Equal(("GPU-PC", "123456", 300, "RTX 4070"), (status!.Name, status.PairingCode, status.CodeExpiresIn, status.Gpu.Name));
        Assert.Equal(["192.168.0.20"], status.Addresses);
    }

    [Fact]
    public async Task A_worker_that_does_not_answer_has_no_status()
    {
        var handler = new Handler(_ => throw new HttpRequestException("refused"));

        Assert.Null(await new WorkerStatusClient(new HttpClient(handler)).GetAsync(8766));
    }

    [Fact]
    public void The_three_languages_have_the_same_texts()
    {
        static HashSet<string> Keys(string file) =>
            [.. XDocument.Load(file).Root!.Elements("data").Select(data => (string)data.Attribute("name")!)];

        var folder = Path.Combine(SourceFolder(), "Resources");
        var english = Keys(Path.Combine(folder, "WorkerStrings.resx"));
        Assert.Equal(english, Keys(Path.Combine(folder, "WorkerStrings.pt-BR.resx")));
        Assert.Equal(english, Keys(Path.Combine(folder, "WorkerStrings.es.resx")));
    }

    [Theory]
    [InlineData("en", "Stop")]
    [InlineData("pt-BR", "Parar")]
    [InlineData("es", "Detener")]
    public void Texts_follow_the_display_language(string culture, string stop)
    {
        var texts = new WorkerTexts(CultureInfo.GetCultureInfo(culture));

        Assert.Equal(stop, texts["WorkerStop"]);
        Assert.All(Enum.GetValues<WorkerState>(), state => Assert.NotEqual($"WorkerState_{state}", texts[$"WorkerState_{state}"]));
        Assert.All(Enum.GetValues<WorkerState>(), state => Assert.NotEqual($"WorkerTag_{state}", texts[$"WorkerTag_{state}"]));
        Assert.Equal("Missing", texts["Missing"]);
    }

    private static string SourceFolder()
    {
        for (var folder = new DirectoryInfo(AppContext.BaseDirectory); folder is not null; folder = folder.Parent)
        {
            var candidate = Path.Combine(folder.FullName, "src", "VozAta.Worker");
            if (Directory.Exists(candidate))
            {
                return candidate;
            }
        }

        throw new DirectoryNotFoundException("src/VozAta.Worker");
    }

    private sealed class Handler(Func<HttpRequestMessage, HttpResponseMessage> answer) : HttpMessageHandler
    {
        public Uri? Uri { get; private set; }

        protected override Task<HttpResponseMessage> SendAsync(HttpRequestMessage request, CancellationToken cancellationToken)
        {
            Uri = request.RequestUri;
            return Task.FromResult(answer(request));
        }
    }
}
