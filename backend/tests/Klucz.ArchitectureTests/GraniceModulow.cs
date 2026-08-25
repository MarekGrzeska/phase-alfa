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
/// w `backend/README.md`.
/// </remarks>
public class GraniceModulow
{
    private static readonly string[] Moduly = ["Klucz.Corpus", "Klucz.Grading", "Klucz.Learning"];

    [Fact]
    public void Moduly_nie_widza_sie_nawzajem()
    {
        foreach (var modul in Moduly)
        {
            var pozostale = Moduly.Where(m => m != modul).ToArray();
            var wynik = Types.InAssembly(Assembly.Load(modul))
                .Should().NotHaveDependencyOnAny(pozostale)
                .GetResult();

            Assert.True(wynik.IsSuccessful,
                $"{modul} sięga do: {string.Join(", ", wynik.FailingTypeNames ?? [])}");
        }
    }

    [Fact]
    public void Nikt_nie_zalezy_od_Api()
    {
        // Api składa moduły w aplikację, więc widzi wszystkich. Zależność w drugą
        // stronę zamieniłaby modularny monolit w kłębek: moduł wiedziałby, w jakiej
        // aplikacji stoi, i nie dałoby się go wyjąć.
        foreach (var nazwa in Moduly.Append("Klucz.Contracts"))
        {
            var wynik = Types.InAssembly(Assembly.Load(nazwa))
                .Should().NotHaveDependencyOn("Klucz.Api")
                .GetResult();

            Assert.True(wynik.IsSuccessful,
                $"{nazwa} sięga do Klucz.Api: {string.Join(", ", wynik.FailingTypeNames ?? [])}");
        }
    }

    [Fact]
    public void Contracts_nie_ma_zaleznosci_zewnetrznych()
    {
        // Contracts opisuje kształt danych i porty. Każdy pakiet dołożony tutaj
        // staje się zależnością WSZYSTKICH modułów naraz — dlatego wolno tu tylko
        // bibliotekę standardową.
        var dozwolone = new[] { "System", "netstandard", "mscorlib" };

        var obce = Assembly.Load("Klucz.Contracts")
            .GetReferencedAssemblies()
            .Select(a => a.Name ?? "")
            .Where(n => !dozwolone.Any(d => n == d || n.StartsWith(d + ".", StringComparison.Ordinal)))
            .ToArray();

        Assert.True(obce.Length == 0,
            $"Klucz.Contracts referuje spoza BCL: {string.Join(", ", obce)}");
    }

    [Fact]
    public void Zaden_modul_nie_dotyka_bazy_bezposrednio()
    {
        // Npgsql wolno TYLKO warstwie Klucz.Corpus.Infrastructure. Reszta pyta bazę
        // przez porty z Contracts — inaczej „moduł nie wie, skąd są dane" przestaje
        // być prawdą i przeniesienie korpusu gdzie indziej dotyka wszystkiego.
        foreach (var nazwa in new[] { "Klucz.Grading", "Klucz.Learning" })
        {
            var wynik = Types.InAssembly(Assembly.Load(nazwa))
                .Should().NotHaveDependencyOn("Npgsql")
                .GetResult();

            Assert.True(wynik.IsSuccessful,
                $"{nazwa} dotyka Npgsql: {string.Join(", ", wynik.FailingTypeNames ?? [])}");
        }

        var pozaInfrastruktura = Types.InAssembly(Assembly.Load("Klucz.Corpus"))
            .That().DoNotResideInNamespace("Klucz.Corpus.Infrastructure")
            .Should().NotHaveDependencyOn("Npgsql")
            .GetResult();

        Assert.True(pozaInfrastruktura.IsSuccessful,
            "Npgsql wyciekł poza Klucz.Corpus.Infrastructure: " +
            string.Join(", ", pozaInfrastruktura.FailingTypeNames ?? []));
    }

    [Fact]
    public void Backend_nie_parsuje_PDF()
    {
        // NAJWAŻNIEJSZA reguła całego projektu (DECYZJE.md): PDF-y otwiera wyłącznie
        // Python. C# czyta gotową strukturę. Test jest tani, a pilnuje granicy, której
        // złamanie jest wygodne w każdym pojedynczym przypadku i katastrofalne w sumie.
        var korzen = KorzenBackendu();

        var podejrzane = Directory.EnumerateFiles(korzen, "*.csproj", SearchOption.AllDirectories)
            .SelectMany(plik => File.ReadLines(plik)
                .Where(linia => linia.Contains("PackageReference", StringComparison.Ordinal)
                                && linia.Contains("pdf", StringComparison.OrdinalIgnoreCase))
                .Select(linia => $"{Path.GetFileName(plik)}: {linia.Trim()}"))
            .ToArray();

        Assert.True(podejrzane.Length == 0,
            "Backend sięgnął po bibliotekę do PDF-ów: " + string.Join(" · ", podejrzane));

        // Drugie sito: pakiet mógł wejść tranzytywnie, bez wpisu w csproj.
        var assembly = new[] { "Klucz.Api", "Klucz.Contracts", "Klucz.Corpus", "Klucz.Grading", "Klucz.Learning" };
        var tranzytywne = assembly
            .SelectMany(n => Assembly.Load(n).GetReferencedAssemblies().Select(a => $"{n} → {a.Name}"))
            .Where(para => para.Contains("pdf", StringComparison.OrdinalIgnoreCase))
            .ToArray();

        Assert.True(tranzytywne.Length == 0,
            "Biblioteka do PDF-ów weszła tranzytywnie: " + string.Join(" · ", tranzytywne));
    }

    /// <summary>Korzeń `backend/` — szukany w górę od katalogu testów, po pliku rozwiązania.</summary>
    private static string KorzenBackendu()
    {
        var katalog = new DirectoryInfo(AppContext.BaseDirectory);
        while (katalog is not null && !File.Exists(Path.Combine(katalog.FullName, "Klucz.sln")))
        {
            katalog = katalog.Parent;
        }

        Assert.NotNull(katalog);
        return katalog!.FullName;
    }
}
