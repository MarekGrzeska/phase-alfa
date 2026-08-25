namespace Klucz.Contracts;

/// <summary>
/// Skład plików binarnych. Bez <c>FileInfo</c> w sygnaturach — przeniesienie na Azure
/// ma być zmianą konfiguracji. Ścieżki zawsze względne wobec korzenia składu.
/// </summary>
public interface IBlobStore
{
    /// <summary>Rzuca <see cref="FileNotFoundException"/>, gdy pliku nie ma.</summary>
    Task<Stream> OpenAsync(string path, CancellationToken ct = default);

    /// <summary>Zwraca ścieżkę względną, pod którą treść stanęła.</summary>
    Task<string> SaveAsync(string path, Stream content, CancellationToken ct = default);

    Task<bool> ExistsAsync(string path, CancellationToken ct = default);
}
