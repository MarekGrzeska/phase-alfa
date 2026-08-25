using Klucz.Contracts;

namespace Klucz.Corpus.Infrastructure;

/// <summary>
/// Skład na dysku lokalnym — implementacja <see cref="IBlobStore"/> na czas alfy.
/// </summary>
/// <remarks>
/// Korzeń bierze się z konfiguracji (<c>Blob:Root</c>, domyślnie <c>data/blob</c>).
/// W bazie stoją ścieżki WZGLĘDNE wobec tego korzenia, więc przeniesienie korpusu
/// na inną maszynę albo do Azure jest zmianą konfiguracji, a nie migracją danych.
/// </remarks>
public sealed class DiskBlobStore : IBlobStore
{
    private readonly string _root;

    public DiskBlobStore(string root)
    {
        // Pełna ścieżka z zakończeniem separatorem — bez niego `/data/blob-obcy`
        // przechodziłby test „zaczyna się od korzenia" dla korzenia `/data/blob`.
        _root = Path.TrimEndingDirectorySeparator(Path.GetFullPath(root)) + Path.DirectorySeparatorChar;
        // Katalog powstaje przy pierwszym zapisie, nie przy konstrukcji: usługi
        // rejestrują się także wtedy, gdy build generuje dokument OpenAPI,
        // a build nie ma prawa tworzyć katalogów z danymi.
    }

    public Task<Stream> OpenAsync(string path, CancellationToken ct = default)
    {
        var full = Expand(path);

        // Jawne sprawdzenie, bo inaczej brak pliku daje RAZ `FileNotFoundException`,
        // a RAZ `DirectoryNotFoundException` — zależnie od tego, czy istnieje katalog
        // nadrzędny. Wywołujący nie ma jak tego rozróżnić i nie powinien musieć:
        // dla niego to jedno zdarzenie, „nie ma takiego bloba".
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

        // Oddajemy ścieżkę WZGLĘDNĄ i zawsze z ukośnikiem w przód: to ona idzie
        // do bazy, a korpus ma się czytać tak samo na Windows i na macOS.
        return Path.GetRelativePath(_root, full).Replace(Path.DirectorySeparatorChar, '/');
    }

    public Task<bool> ExistsAsync(string path, CancellationToken ct = default)
        => Task.FromResult(File.Exists(Expand(path)));

    /// <summary>Ścieżka względna → pełna, z pilnowaniem, że nie wychodzi poza korzeń.</summary>
    /// <remarks>
    /// `..` w nazwie pliku nie jest scenariuszem z bajki, gdy nazwy biorą się z tekstu
    /// PDF-a. Normalizujemy najpierw (`GetFullPath` zjada `..`), a dopiero potem
    /// porównujemy z korzeniem — odwrotna kolejność przepuszcza `a/../../etc`.
    /// </remarks>
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
