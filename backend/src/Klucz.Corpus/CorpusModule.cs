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
/// gdyby rejestracja wymagała bazy, <c>dotnet build</c> wymagałby postawionego Postgresa.
/// </remarks>
public static class CorpusModule
{
    public static IServiceCollection AddCorpus(this IServiceCollection services, IConfiguration configuration)
    {
        // `configuration` w sygnaturze zostaje: trzy metody `Add*` mają wyglądać
        // tak samo, a moduły A2–A4 będą jej potrzebować. Rejestracje poniżej biorą
        // konfigurację z kontenera, żeby czytać ją PÓŹNIEJ, nie w tym miejscu.
        services.AddSingleton<IDatabaseProbe, PostgresDatabaseProbe>();

        // Skład blobów powstaje przy PIERWSZYM UŻYCIU, nie tutaj — z tego samego
        // powodu co leniwy adres bazy. `RepositoryRoot.Resolve` chodzi po dysku
        // w górę katalogów, a ta metoda ma tylko rejestrować. Poza tym konfiguracja
        // bywa dokładana PO rejestracji usług (tak robi `WebApplicationFactory`
        // w testach), więc odczyt w tym miejscu nie widziałby nadpisań i „korzeń
        // z konfiguracji" nie dałoby się sprawdzić testem.
        services.AddSingleton<IBlobStore>(provider =>
        {
            var settings = provider.GetRequiredService<IConfiguration>();

            // Korzeń składu jest WZGLĘDNY wobec korzenia repozytorium, tak samo jak
            // `BLOB_ROOT` po stronie Pythona — w bazie stoją ścieżki względne.
            //
            // KOLEJNOŚĆ MA ZNACZENIE: zmienna środowiskowa stoi PIERWSZA. `Blob:Root`
            // jest w `appsettings.json`, więc zawsze coś zwraca — postawiony przed
            // `BLOB_ROOT` zjadałby go w całości i zmienna z `.env` nie wykonałaby się
            // nigdy, mimo że `.env.example` i `backend/README.md` obiecują, że to nią
            // przenosi się skład na inny dysk. Objawem byłby korpus w dwóch miejscach:
            // Python pisze w nowym, C# czyta ze starego, i nic o tym nie mówi.
            var blobRoot = settings["BLOB_ROOT"] ?? settings["Blob:Root"] ?? "data/blob";

            return new DiskBlobStore(RepositoryRoot.Resolve(blobRoot));
        });

        return services;
    }
}
