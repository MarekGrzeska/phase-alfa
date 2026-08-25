namespace Klucz.Corpus.Infrastructure;

/// <summary>
/// Korzeń repozytorium, tak samo jak w <c>ingest/sciezki.py</c>. Licząc od katalogu
/// roboczego, <c>data/blob</c> lądowałoby tam, gdzie parser nie pisze.
/// </summary>
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

    public static string Resolve(string path)
        => Path.IsPathRooted(path) ? path : Path.GetFullPath(Path.Combine(Find(), path));
}
