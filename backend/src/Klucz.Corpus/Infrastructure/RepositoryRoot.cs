namespace Klucz.Corpus.Infrastructure;

/// <summary>
/// Korzeń repozytorium — punkt odniesienia dla ścieżek względnych z konfiguracji.
/// </summary>
/// <remarks>
/// <c>.env</c> obiecuje, że <c>BLOB_ROOT</c> jest liczony od KORZENIA REPOZYTORIUM, i tak
/// robi to Python (<c>ingest/sciezki.py</c>). Gdyby C# liczył od katalogu roboczego,
/// ta sama wartość w tym samym pliku znaczyłaby co innego dla obu warstw: <c>dotnet run</c>
/// ustawia katalog roboczy na katalog projektu, więc <c>data/blob</c> lądowałoby
/// w <c>backend/src/Klucz.Api/data/blob</c>, a nie tam, gdzie pisze parser.
///
/// Szukamy w górę pliku <c>Taskfile.yml</c> — jednego wejścia do wszystkich pętli,
/// które z definicji leży w korzeniu. Gdy go nie ma (opublikowana aplikacja poza
/// repozytorium), zostaje katalog roboczy i to jest świadomy wybór: w produkcji
/// ścieżka i tak przychodzi absolutna albo z Azure.
/// </remarks>
public static class RepositoryRoot
{
    public static string Find(string? start = null)
    {
        var directory = new DirectoryInfo(start ?? AppContext.BaseDirectory);
        while (directory is not null)
        {
            if (File.Exists(Path.Combine(directory.FullName, "Taskfile.yml")))
            {
                return directory.FullName;
            }

            directory = directory.Parent;
        }

        return Directory.GetCurrentDirectory();
    }

    /// <summary>Ścieżka z konfiguracji → absolutna. Względna liczy się od korzenia repozytorium.</summary>
    public static string Resolve(string path)
        => Path.IsPathRooted(path) ? path : Path.GetFullPath(Path.Combine(Find(), path));
}
