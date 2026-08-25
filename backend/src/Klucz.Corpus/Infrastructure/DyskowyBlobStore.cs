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
public sealed class DyskowyBlobStore : IBlobStore
{
    private readonly string _korzen;

    public DyskowyBlobStore(string korzen)
    {
        // Pełna ścieżka z zakończeniem separatorem — bez niego `/data/blob-obcy`
        // przechodziłby test „zaczyna się od korzenia" dla korzenia `/data/blob`.
        _korzen = Path.TrimEndingDirectorySeparator(Path.GetFullPath(korzen))
                  + Path.DirectorySeparatorChar;
        // Katalog powstaje przy pierwszym zapisie, nie przy konstrukcji: usługi
        // rejestrują się także wtedy, gdy build generuje dokument OpenAPI,
        // a build nie ma prawa tworzyć katalogów z danymi.
    }

    public Task<Stream> OtworzAsync(string sciezka, CancellationToken ct = default)
    {
        var pelna = Rozwin(sciezka);

        // Jawne sprawdzenie, bo inaczej brak pliku daje RAZ `FileNotFoundException`,
        // a RAZ `DirectoryNotFoundException` — zależnie od tego, czy istnieje katalog
        // nadrzędny. Wywołujący nie ma jak tego rozróżnić i nie powinien musieć:
        // dla niego to jedno zdarzenie, „nie ma takiego bloba".
        if (!File.Exists(pelna))
        {
            throw new FileNotFoundException($"Brak bloba: {sciezka}", sciezka);
        }

        Stream strumien = new FileStream(pelna, FileMode.Open, FileAccess.Read, FileShare.Read);
        return Task.FromResult(strumien);
    }

    public async Task<string> ZapiszAsync(string sciezka, Stream tresc, CancellationToken ct = default)
    {
        var pelna = Rozwin(sciezka);
        Directory.CreateDirectory(Path.GetDirectoryName(pelna)!);

        await using (var plik = new FileStream(pelna, FileMode.Create, FileAccess.Write, FileShare.None))
        {
            await tresc.CopyToAsync(plik, ct);
        }

        // Oddajemy ścieżkę WZGLĘDNĄ i zawsze z ukośnikiem w przód: to ona idzie
        // do bazy, a korpus ma się czytać tak samo na Windows i na macOS.
        return Path.GetRelativePath(_korzen, pelna).Replace(Path.DirectorySeparatorChar, '/');
    }

    public Task<bool> IstniejeAsync(string sciezka, CancellationToken ct = default)
        => Task.FromResult(File.Exists(Rozwin(sciezka)));

    /// <summary>Ścieżka względna → pełna, z pilnowaniem, że nie wychodzi poza korzeń.</summary>
    /// <remarks>
    /// `..` w nazwie pliku nie jest scenariuszem z bajki, gdy nazwy biorą się z tekstu
    /// PDF-a. Normalizujemy najpierw (`GetFullPath` zjada `..`), a dopiero potem
    /// porównujemy z korzeniem — odwrotna kolejność przepuszcza `a/../../etc`.
    /// </remarks>
    private string Rozwin(string sciezka)
    {
        if (string.IsNullOrWhiteSpace(sciezka))
        {
            throw new ArgumentException("Pusta ścieżka w składzie blobów.", nameof(sciezka));
        }

        if (Path.IsPathRooted(sciezka))
        {
            throw new ArgumentException(
                $"Ścieżka w składzie ma być względna, a jest absolutna: {sciezka}", nameof(sciezka));
        }

        var pelna = Path.GetFullPath(Path.Combine(_korzen, sciezka));
        if (!pelna.StartsWith(_korzen, StringComparison.Ordinal))
        {
            throw new ArgumentException(
                $"Ścieżka wychodzi poza korzeń składu: {sciezka}", nameof(sciezka));
        }

        return pelna;
    }
}
