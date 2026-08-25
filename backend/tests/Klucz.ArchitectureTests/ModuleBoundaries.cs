using System.Reflection;
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
/// </remarks>
public class ModuleBoundaries
{
    private static readonly string[] Modules = ["Klucz.Corpus", "Klucz.Grading", "Klucz.Learning"];

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
        foreach (var name in new[] { "Klucz.Grading", "Klucz.Learning" })
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
    }

    [Fact]
    public void Backend_does_not_parse_PDF()
    {
        // NAJWAŻNIEJSZA reguła całego projektu (DECYZJE.md): PDF-y otwiera wyłącznie
        // Python. C# czyta gotową strukturę. Test jest tani, a pilnuje granicy, której
        // złamanie jest wygodne w każdym pojedynczym przypadku i katastrofalne w sumie.
        var root = BackendRoot();

        var suspicious = Directory.EnumerateFiles(root, "*.csproj", SearchOption.AllDirectories)
            .SelectMany(file => File.ReadLines(file)
                .Where(line => line.Contains("PackageReference", StringComparison.Ordinal)
                               && line.Contains("pdf", StringComparison.OrdinalIgnoreCase))
                .Select(line => $"{Path.GetFileName(file)}: {line.Trim()}"))
            .ToArray();

        Assert.True(suspicious.Length == 0,
            "Backend sięgnął po bibliotekę do PDF-ów: " + string.Join(" · ", suspicious));

        // Drugie sito: pakiet mógł wejść tranzytywnie, bez wpisu w csproj.
        var assemblies = new[] { "Klucz.Api", "Klucz.Contracts", "Klucz.Corpus", "Klucz.Grading", "Klucz.Learning" };
        var transitive = assemblies
            .SelectMany(name => Assembly.Load(name).GetReferencedAssemblies().Select(a => $"{name} → {a.Name}"))
            .Where(pair => pair.Contains("pdf", StringComparison.OrdinalIgnoreCase))
            .ToArray();

        Assert.True(transitive.Length == 0,
            "Biblioteka do PDF-ów weszła tranzytywnie: " + string.Join(" · ", transitive));
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
