using System.Reflection;
using System.Text.Json;
using System.Text.RegularExpressions;
using NetArchTest.Rules;

namespace Klucz.ArchitectureTests;

/// <summary>
/// Granice modułów egzekwowane testem, nie umową.
/// </summary>
/// <remarks>
/// Te testy istnieją od pierwszego commita backendu celowo: dokładanie modułów
/// w A2–A4 ma być dopisywaniem, nie przebudową. Granica, której nikt nie pilnuje,
/// znika przy trzecim „na razie zaimportuję to bezpośrednio".
///
/// Każdy z tych testów był raz widziany NA CZERWONO — bez tego byłby dekoracją
/// (patrz CLAUDE.md, „Testy, które nic nie sprawdzają"). Sposób sprawdzenia stoi
/// w <c>backend/README.md</c>.
///
/// TRZY RÓŻNE SITA, bo każde widzi co innego i żadne nie zastępuje pozostałych:
/// <list type="bullet">
/// <item>referencje assembly (<c>GetReferencedAssemblies</c>, NetArchTest) — widzą to,
///   czego kod FAKTYCZNIE UŻYWA; pakiet dopisany, ale jeszcze nie zawołany, jest dla
///   nich niewidoczny, bo kompilator nie emituje referencji do assembly, z którego
///   nic nie wzięto;</item>
/// <item>deklaracje w <c>*.csproj</c> i <c>Directory.Packages.props</c> — widzą zamiar,
///   zanim ktokolwiek go użyje;</item>
/// <item><c>obj/project.assets.json</c> — pełne domknięcie tranzytywne po
///   <c>restore</c>, także pakietów nieużytych w kodzie.</item>
/// </list>
/// </remarks>
public class ModuleBoundaries
{
    private static readonly string[] Modules = ["Klucz.Corpus", "Klucz.Grading", "Klucz.Learning"];

    /// <summary>
    /// Biblioteki do PDF-ów po NAZWIE, nie po podciągu „pdf".
    /// </summary>
    /// <remarks>
    /// Samo dopasowanie podciągu przepuszczało dwie najpopularniejsze biblioteki PDF
    /// dla .NET: <c>itext7</c> i <c>Docnet.Core</c> — żadna nie ma „pdf" w nazwie.
    /// Podciąg zostaje jako drugie kryterium, bo łapie warianty pisowni
    /// (<c>PdfPig</c>, <c>PDFsharp</c>, <c>Syncfusion.Pdf.Net.Core</c>).
    /// </remarks>
    private static readonly string[] PdfLibraries =
    [
        "itext7", "itext", "iTextSharp", "Docnet.Core", "QuestPDF",
        "PdfPig", "UglyToad.PdfPig", "PDFsharp", "PdfSharpCore",
        "Syncfusion.Pdf", "Aspose.Pdf", "IronPdf", "Spire.PDF", "Patagames.Pdf",
    ];

    /// <summary>Wpis <c>PackageReference</c> albo <c>PackageVersion</c> w pliku MSBuild.</summary>
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
        // Api składa moduły w aplikację, więc widzi wszystkich. Zależność w drugą
        // stronę zamieniłaby modularny monolit w kłębek: moduł wiedziałby, w jakiej
        // aplikacji stoi, i nie dałoby się go wyjąć.
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
        // Contracts opisuje kształt danych i porty. Każdy pakiet dołożony tutaj
        // staje się zależnością WSZYSTKICH modułów naraz — dlatego wolno tu tylko
        // bibliotekę standardową.
        var project = Path.Combine(BackendRoot(), "src", "Klucz.Contracts");

        // Sito 1 — DEKLARACJA. Bez niego `<PackageReference Include="Newtonsoft.Json" />`
        // dopisany do csproj przechodził bez protestu, a pakiet od tej chwili płynął
        // tranzytywnie do wszystkich modułów. Czerwono robiło się dopiero przy commicie,
        // który go UŻYWA — czyli wtedy, gdy granica jest już przekroczona i test
        // przestaje być granicą, a staje się protokołem z wypadku.
        var declared = PackagesDeclaredIn(Path.Combine(project, "Klucz.Contracts.csproj"));
        Assert.True(declared.Length == 0,
            $"Klucz.Contracts.csproj deklaruje pakiety: {string.Join(", ", declared)}");

        // Sito 2 — domknięcie tranzytywne po restore.
        var restored = PackagesInAssets(project);
        Assert.True(restored.Length == 0,
            $"Klucz.Contracts ma po restore pakiety: {string.Join(", ", restored)}");

        // Sito 3 — to, co faktycznie wyszło z kompilacji.
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
        // Npgsql wolno TYLKO warstwie Klucz.Corpus.Infrastructure. Reszta pyta bazę
        // przez porty z Contracts — inaczej „moduł nie wie, skąd są dane" przestaje
        // być prawdą i przeniesienie korpusu gdzie indziej dotyka wszystkiego.
        //
        // Klucz.Api JEST na tej liście, choć składa wszystkie moduły: kompozycja
        // dostaje gotowy port i sterownika bazy nie potrzebuje. Bez tego wpisu
        // `new NpgsqlConnection(...)` dopisane wprost w Program.cs przechodziło
        // wszystkie bramki, mimo że backend/README.md obiecuje, że `Infrastructure/`
        // to JEDYNE miejsce z Npgsql.
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

        // Sito na DEKLARACJACH. Powyższe widzą UŻYCIE, więc zapalają się dopiero po
        // fakcie; sam wpis w csproj jest zaproszeniem, żeby ten fakt nastąpił.
        // Sprawdzamy `src/` — projekty testowe łączą się z bazą świadomie
        // (`RequiresDatabaseFact`) i mają do tego prawo.
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
        // NAJWAŻNIEJSZA reguła całego projektu (DECYZJE.md): PDF-y otwiera wyłącznie
        // Python. C# czyta gotową strukturę. Test jest tani, a pilnuje granicy, której
        // złamanie jest wygodne w każdym pojedynczym przypadku i katastrofalne w sumie.
        var root = BackendRoot();

        // Sito 1 — DEKLARACJE. Razem z `Directory.Packages.props`, bo od wprowadzenia
        // centralnych wersji to TAM stoją numery, a `<PackageVersion Include="PdfPig" />`
        // bez wpisu w żadnym csproj jest pierwszym krokiem do dołożenia go za chwilę.
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

        // Sito 2 — DOMKNIĘCIE TRANZYTYWNE z `obj/project.assets.json`. Stało tu wcześniej
        // `GetReferencedAssemblies()`, które zwraca wyłącznie referencje faktycznie użyte
        // w kodzie — pakiet, który wszedł tranzytywnie i którego nikt jeszcze nie zawołał,
        // był dla tego sita niewidoczny. Plik po restore zawiera całe drzewo.
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

    /// <summary>Czy nazwa pakietu to biblioteka do PDF-ów — po liście znanych nazw i po podciągu.</summary>
    private static bool IsPdfLibrary(string package)
        => package.Contains("pdf", StringComparison.OrdinalIgnoreCase)
           || PdfLibraries.Any(known => package.StartsWith(known, StringComparison.OrdinalIgnoreCase));

    /// <summary>Nazwy pakietów zadeklarowane w pliku MSBuild.</summary>
    private static string[] PackagesDeclaredIn(string file)
        => File.Exists(file)
            ? PackageDeclaration.Matches(File.ReadAllText(file))
                .Select(match => match.Groups[1].Value)
                .ToArray()
            : [];

    /// <summary>
    /// Nazwy pakietów NuGet z <c>obj/project.assets.json</c> — całe drzewo po <c>restore</c>.
    /// </summary>
    /// <remarks>
    /// Odsiewamy wpisy typu <c>project</c>: referencje projektowe stoją w tej samej
    /// sekcji co pakiety, a granic między projektami pilnuje NetArchTest.
    /// </remarks>
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
            .Where(library => library.Value.TryGetProperty("type", out var type)
                              && type.GetString() == "package")
            .Select(library => library.Name.Split('/')[0])
            .ToArray();
    }

    /// <summary>Korzeń <c>backend/</c> — szukany w górę od katalogu testów, po pliku rozwiązania.</summary>
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
