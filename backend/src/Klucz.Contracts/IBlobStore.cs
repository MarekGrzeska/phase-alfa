namespace Klucz.Contracts;

/// <summary>
/// Skład plików binarnych: wycinki stron, PDF-y źródłowe, cokolwiek, co nie jest wierszem w bazie.
/// </summary>
/// <remarks>
/// Port, nie klasa — przeniesienie na Azure po alfie ma być zmianą konfiguracji,
/// nie zmianą architektury. Dlatego w sygnaturach nie ma <c>FileInfo</c> ani
/// <c>DirectoryInfo</c>: nic tu nie zdradza, że pod spodem dziś jest dysk.
///
/// Ścieżka jest ZAWSZE względna wobec korzenia składu (<c>OMAP/2025-05-01/100/X/z16-0.png</c>)
/// i takie ścieżki stoją w bazie. Absolutna ścieżka albo litera dysku zabija
/// przenośność korpusu między maszynami.
/// </remarks>
public interface IBlobStore
{
    /// <summary>Otwiera plik do odczytu. Rzuca, gdy pliku nie ma.</summary>
    Task<Stream> OtworzAsync(string sciezka, CancellationToken ct = default);

    /// <summary>Zapisuje treść pod wskazaną ścieżką i zwraca ścieżkę względną, pod którą stanęła.</summary>
    Task<string> ZapiszAsync(string sciezka, Stream tresc, CancellationToken ct = default);

    /// <summary>Czy plik istnieje. Nie rzuca.</summary>
    Task<bool> IstniejeAsync(string sciezka, CancellationToken ct = default);
}
