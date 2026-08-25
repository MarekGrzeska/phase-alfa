using Klucz.Contracts;
using Klucz.Corpus.Infrastructure;
using Microsoft.Extensions.Configuration;
using Microsoft.Extensions.DependencyInjection;

namespace Klucz.Corpus;

/// <summary>
/// Wejście modułu korpusu — jedna metoda, którą woła <c>Program.cs</c>.
/// </summary>
/// <remarks>
/// <c>Program.cs</c> ma wołać trzy linijki i nie znać wnętrza modułów. Dzięki temu
/// dołożenie czwartego modułu w A2 jest dopisaniem linijki, a nie przebudową
/// kompozycji.
///
/// Rejestracja niczego nie sprawdza i niczego nie otwiera: ani bazy, ani dysku.
/// Build generuje dokument OpenAPI, a żeby go wygenerować, startuje aplikację —
/// gdyby rejestracja wymagała bazy, `dotnet build` wymagałby postawionego Postgresa.
/// </remarks>
public static class CorpusModule
{
    public static IServiceCollection AddCorpus(this IServiceCollection uslugi, IConfiguration konfiguracja)
    {
        uslugi.AddSingleton<IDatabaseProbe, PostgresDatabaseProbe>();

        // Korzeń składu jest WZGLĘDNY wobec korzenia repozytorium, tak samo jak
        // `BLOB_ROOT` po stronie Pythona — w bazie stoją ścieżki względne.
        var korzenBlobow = konfiguracja["Blob:Root"] ?? konfiguracja["BLOB_ROOT"] ?? "data/blob";
        uslugi.AddSingleton<IBlobStore>(new DyskowyBlobStore(KorzenRepozytorium.Rozwin(korzenBlobow)));

        return uslugi;
    }
}
