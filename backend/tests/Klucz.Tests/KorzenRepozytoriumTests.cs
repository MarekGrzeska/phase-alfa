using Klucz.Corpus.Infrastructure;

namespace Klucz.Tests;

/// <summary>
/// Ścieżki z konfiguracji liczą się od korzenia repozytorium, nie od katalogu procesu.
/// </summary>
public class KorzenRepozytoriumTests
{
    [Fact]
    public void Wzgledna_sciezka_konfiguracji_ląduje_w_korzeniu_repozytorium()
    {
        // `dotnet run` ustawia katalog roboczy na katalog projektu. Gdyby `data/blob`
        // liczyło się od niego, korpus pisany przez Pythona i czytany przez C# stałby
        // w dwóch różnych miejscach — mimo tej samej wartości w tym samym `.env`.
        var korzen = KorzenRepozytorium.Znajdz();
        var rozwinieta = KorzenRepozytorium.Rozwin("data/blob");

        Assert.True(File.Exists(Path.Combine(korzen, "Taskfile.yml")),
            $"korzeń repozytorium wskazany na {korzen}, a nie ma tam Taskfile.yml");
        Assert.Equal(Path.Combine(korzen, "data", "blob"), rozwinieta);
    }

    [Fact]
    public void Sciezka_absolutna_zostaje_nietknieta()
    {
        var absolutna = Path.Combine(Path.GetTempPath(), "blob");

        Assert.Equal(absolutna, KorzenRepozytorium.Rozwin(absolutna));
    }
}
