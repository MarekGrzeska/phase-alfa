using Klucz.Contracts;

namespace Klucz.Corpus.Infrastructure;

/// <summary>Skład na dysku lokalnym — implementacja <see cref="IBlobStore"/> na czas alfy.</summary>
public sealed class DiskBlobStore : IBlobStore
{
    private readonly string _root;

    public DiskBlobStore(string root)
    {
        // Zakończenie separatorem: bez niego `/data/blob-obcy` przechodzi test
        // „zaczyna się od korzenia" dla korzenia `/data/blob`.
        _root = Path.TrimEndingDirectorySeparator(Path.GetFullPath(root)) + Path.DirectorySeparatorChar;
    }

    /// <summary>Wystawiony, żeby test sprawdził GDZIE stanął skład, nie tylko że się zarejestrował.</summary>
    public string Root => _root;

    public Task<Stream> OpenAsync(string path, CancellationToken ct = default)
    {
        var full = Expand(path);

        // Bez tego brak pliku daje raz `FileNotFoundException`, a raz `DirectoryNotFoundException`.
        if (!File.Exists(full))
        {
            throw new FileNotFoundException($"Brak bloba: {path}", path);
        }

        Stream stream = new FileStream(full, FileMode.Open, FileAccess.Read, FileShare.Read);
        return Task.FromResult(stream);
    }

    public async Task<string> SaveAsync(string path, Stream content, CancellationToken ct = default)
    {
        var full = Expand(path);
        Directory.CreateDirectory(Path.GetDirectoryName(full)!);

        await using (var file = new FileStream(full, FileMode.Create, FileAccess.Write, FileShare.None))
        {
            await content.CopyToAsync(file, ct);
        }

        // Ścieżka względna i z ukośnikiem w przód: idzie do bazy, a korpus ma się czytać
        // tak samo na Windows i na macOS.
        return Path.GetRelativePath(_root, full).Replace(Path.DirectorySeparatorChar, '/');
    }

    public Task<bool> ExistsAsync(string path, CancellationToken ct = default)
        => Task.FromResult(File.Exists(Expand(path)));

    /// <summary>Normalizacja PRZED porównaniem z korzeniem — odwrotna kolejność przepuszcza `a/../../etc`.</summary>
    private string Expand(string path)
    {
        if (string.IsNullOrWhiteSpace(path))
        {
            throw new ArgumentException("Pusta ścieżka w składzie blobów.", nameof(path));
        }

        if (Path.IsPathRooted(path))
        {
            throw new ArgumentException(
                $"Ścieżka w składzie ma być względna, a jest absolutna: {path}", nameof(path));
        }

        var full = Path.GetFullPath(Path.Combine(_root, path));
        if (!full.StartsWith(_root, StringComparison.Ordinal))
        {
            throw new ArgumentException($"Ścieżka wychodzi poza korzeń składu: {path}", nameof(path));
        }

        return full;
    }
}
