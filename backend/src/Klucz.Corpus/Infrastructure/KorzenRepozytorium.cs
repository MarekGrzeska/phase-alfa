namespace Klucz.Corpus.Infrastructure;

/// <summary>
/// Korzeń repozytorium — punkt odniesienia dla ścieżek względnych z konfiguracji.
/// </summary>
/// <remarks>
/// `.env` obiecuje, że <c>BLOB_ROOT</c> jest liczony od KORZENIA REPOZYTORIUM, i tak
/// robi to Python (<c>ingest/sciezki.py</c>). Gdyby C# liczył od katalogu roboczego,
/// ta sama wartość w tym samym pliku znaczyłaby co innego dla obu warstw: `dotnet run`
/// ustawia katalog roboczy na katalog projektu, więc <c>data/blob</c> lądowałoby
/// w <c>backend/src/Klucz.Api/data/blob</c>, a nie tam, gdzie pisze parser.
///
/// Szukamy w górę pliku <c>Taskfile.yml</c> — jednego wejścia do wszystkich pętli,
/// które z definicji leży w korzeniu. Gdy go nie ma (opublikowana aplikacja poza
/// repozytorium), zostaje katalog roboczy i to jest świadomy wybór: w produkcji
/// ścieżka i tak przychodzi absolutna albo z Azure.
/// </remarks>
public static class KorzenRepozytorium
{
    public static string Znajdz(string? start = null)
    {
        var katalog = new DirectoryInfo(start ?? AppContext.BaseDirectory);
        while (katalog is not null)
        {
            if (File.Exists(Path.Combine(katalog.FullName, "Taskfile.yml")))
            {
                return katalog.FullName;
            }

            katalog = katalog.Parent;
        }

        return Directory.GetCurrentDirectory();
    }

    /// <summary>Ścieżka z konfiguracji → absolutna. Względna liczy się od korzenia repozytorium.</summary>
    public static string Rozwin(string sciezka)
        => Path.IsPathRooted(sciezka) ? sciezka : Path.GetFullPath(Path.Combine(Znajdz(), sciezka));
}
