using System.Reflection;
using System.Text.Json;
using System.Text.RegularExpressions;
using NetArchTest.Rules;

namespace Klucz.ArchitectureTests;

/// <summary>
/// Granice modułów egzekwowane testem. Każdy był raz widziany NA CZERWONO — sposób
/// sprawdzenia stoi w <c>backend/README.md</c>. Trzy sita, bo każde widzi co innego:
/// referencje assembly (użycie), deklaracje w csproj (zamiar) i <c>project.assets.json</c>
/// (domknięcie tranzytywne po restore).
/// </summary>
public class ModuleBoundaries
{
    private static readonly string[] Modules = ["Klucz.Corpus", "Klucz.Grading", "Klucz.Learning"];

    // Po NAZWIE, bo sam podciąg „pdf" przepuszcza itext7 i Docnet.Core.
    private static readonly string[] PdfLibraries =
    [
        "itext7", "itext", "iTextSharp", "Docnet.Core", "QuestPDF",
        "PdfPig", "UglyToad.PdfPig", "PDFsharp", "PdfSharpCore",
        "Syncfusion.Pdf", "Aspose.Pdf", "IronPdf", "Spire.PDF", "Patagames.Pdf",
    ];

    private static readonly Regex PackageDeclaration =
        new("<Package(?:Reference|Version)\\s[^>]*Include=\"([^\"]+)\"", RegexOptions.Compiled);

    [Fact]
    public void Modules_do_not_see_each_other()
    {
        foreach (var module in Modules)
        {
            var others = Modules.Where(m => m != module).ToArray();
            var result = Types.InAssembly(Assembly.Load(module))
                .Should().NotHaveDependencyOnAny(others)
                .GetResult();

            Assert.True(result.IsSuccessful,
                $"{module} sięga do: {string.Join(", ", result.FailingTypeNames ?? [])}");
        }
    }

    [Fact]
    public void Nothing_depends_on_Api()
    {
        foreach (var name in Modules.Append("Klucz.Contracts"))
        {
            var result = Types.InAssembly(Assembly.Load(name))
                .Should().NotHaveDependencyOn("Klucz.Api")
                .GetResult();

            Assert.True(result.IsSuccessful,
                $"{name} sięga do Klucz.Api: {string.Join(", ", result.FailingTypeNames ?? [])}");
        }
    }

    [Fact]
    public void Contracts_has_no_external_dependencies()
    {
        var project = Path.Combine(BackendRoot(), "src", "Klucz.Contracts");

        // Sito na deklaracjach: pakiet dopisany do csproj płynie tranzytywnie do wszystkich
        // modułów, a pozostałe sita widzą go dopiero przy commicie, który go UŻYWA.
        var declared = PackagesDeclaredIn(Path.Combine(project, "Klucz.Contracts.csproj"));
        Assert.True(declared.Length == 0,
            $"Klucz.Contracts.csproj deklaruje pakiety: {string.Join(", ", declared)}");

        var restored = PackagesInAssets(project);
        Assert.True(restored.Length == 0,
            $"Klucz.Contracts ma po restore pakiety: {string.Join(", ", restored)}");

        var allowed = new[] { "System", "netstandard", "mscorlib" };

        var foreign = Assembly.Load("Klucz.Contracts")
            .GetReferencedAssemblies()
            .Select(a => a.Name ?? "")
            .Where(name => !allowed.Any(a => name == a || name.StartsWith(a + ".", StringComparison.Ordinal)))
            .ToArray();

        Assert.True(foreign.Length == 0,
            $"Klucz.Contracts referuje spoza BCL: {string.Join(", ", foreign)}");
    }

    [Fact]
    public void No_module_touches_the_database_directly()
    {
        // Klucz.Api jest na liście, choć składa moduły: dostaje gotowy port i sterownika
        // bazy nie potrzebuje.
        foreach (var name in new[] { "Klucz.Api", "Klucz.Grading", "Klucz.Learning" })
        {
            var result = Types.InAssembly(Assembly.Load(name))
                .Should().NotHaveDependencyOn("Npgsql")
                .GetResult();

            Assert.True(result.IsSuccessful,
                $"{name} dotyka Npgsql: {string.Join(", ", result.FailingTypeNames ?? [])}");
        }

        var outsideInfrastructure = Types.InAssembly(Assembly.Load("Klucz.Corpus"))
            .That().DoNotResideInNamespace("Klucz.Corpus.Infrastructure")
            .Should().NotHaveDependencyOn("Npgsql")
            .GetResult();

        Assert.True(outsideInfrastructure.IsSuccessful,
            "Npgsql wyciekł poza Klucz.Corpus.Infrastructure: " +
            string.Join(", ", outsideInfrastructure.FailingTypeNames ?? []));

        // Tylko `src/` — projekty testowe łączą się z bazą świadomie (`RequiresDatabaseFact`).
        var declaringNpgsql = Directory
            .EnumerateFiles(Path.Combine(BackendRoot(), "src"), "*.csproj", SearchOption.AllDirectories)
            .Where(file => PackagesDeclaredIn(file)
                .Any(name => name.Equals("Npgsql", StringComparison.OrdinalIgnoreCase)))
            .Select(Path.GetFileName)
            .Order(StringComparer.Ordinal)
            .ToArray();

        Assert.True(declaringNpgsql is ["Klucz.Corpus.csproj"],
            "Npgsql wolno deklarować wyłącznie w Klucz.Corpus.csproj, a deklarują go: " +
            string.Join(", ", declaringNpgsql));
    }

    [Fact]
    public void Backend_does_not_parse_PDF()
    {
        // NAJWAŻNIEJSZA reguła projektu (DECYZJE.md): PDF-y otwiera wyłącznie Python.
        var root = BackendRoot();

        var declarations = Directory
            .EnumerateFiles(root, "*.csproj", SearchOption.AllDirectories)
            .Append(Path.Combine(root, "Directory.Packages.props"))
            .Where(File.Exists)
            .SelectMany(file => PackagesDeclaredIn(file)
                .Where(IsPdfLibrary)
                .Select(name => $"{Path.GetFileName(file)}: {name}"))
            .ToArray();

        Assert.True(declarations.Length == 0,
            "Backend sięgnął po bibliotekę do PDF-ów: " + string.Join(" · ", declarations));

        var projects = Directory
            .EnumerateFiles(root, "*.csproj", SearchOption.AllDirectories)
            .Select(Path.GetDirectoryName)
            .OfType<string>()
            .ToArray();

        Assert.NotEmpty(projects);

        var transitive = projects
            .SelectMany(directory => PackagesInAssets(directory)
                .Where(IsPdfLibrary)
                .Select(name => $"{Path.GetFileName(directory)} → {name}"))
            .Distinct(StringComparer.Ordinal)
            .ToArray();

        Assert.True(transitive.Length == 0,
            "Biblioteka do PDF-ów weszła tranzytywnie: " + string.Join(" · ", transitive));
    }

    private static bool IsPdfLibrary(string package)
        => package.Contains("pdf", StringComparison.OrdinalIgnoreCase)
           || PdfLibraries.Any(known => package.StartsWith(known, StringComparison.OrdinalIgnoreCase));

    private static string[] PackagesDeclaredIn(string file)
        => File.Exists(file)
            ? PackageDeclaration.Matches(File.ReadAllText(file))
                .Select(match => match.Groups[1].Value)
                .ToArray()
            : [];

    private static string[] PackagesInAssets(string projectDirectory)
    {
        var assets = Path.Combine(projectDirectory, "obj", "project.assets.json");
        if (!File.Exists(assets))
        {
            return [];
        }

        using var document = JsonDocument.Parse(File.ReadAllText(assets));
        if (!document.RootElement.TryGetProperty("libraries", out var libraries))
        {
            return [];
        }

        return libraries.EnumerateObject()
            // Wpisy typu `project` odsiewamy: granic między projektami pilnuje NetArchTest.
            .Where(library => library.Value.TryGetProperty("type", out var type)
                              && type.GetString() == "package")
            .Select(library => library.Name.Split('/')[0])
            .ToArray();
    }

    private static string BackendRoot()
    {
        var directory = new DirectoryInfo(AppContext.BaseDirectory);
        while (directory is not null && !File.Exists(Path.Combine(directory.FullName, "Klucz.sln")))
        {
            directory = directory.Parent;
        }

        Assert.NotNull(directory);
        return directory!.FullName;
    }
}
