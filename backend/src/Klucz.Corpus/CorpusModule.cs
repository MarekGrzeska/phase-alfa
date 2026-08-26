using Klucz.Contracts;
using Klucz.Corpus.Infrastructure;
using Microsoft.Extensions.Configuration;
using Microsoft.Extensions.DependencyInjection;

namespace Klucz.Corpus;

/// <summary>Wejście modułu korpusu — jedna metoda, którą woła <c>Program.cs</c>.</summary>
public static class CorpusModule
{
    public static IServiceCollection AddCorpus(this IServiceCollection services, IConfiguration configuration)
    {
        services.AddSingleton<IDatabaseProbe, PostgresDatabaseProbe>();
        services.AddSingleton<ICorpusReader, PostgresCorpusReader>();

        services.AddSingleton<IBlobStore>(provider =>
        {
            // Konfigurację czytamy przy pierwszym użyciu: `WebApplicationFactory` dokłada
            // ją PO rejestracji usług, a odczyt tutaj nie widziałby nadpisań.
            var settings = provider.GetRequiredService<IConfiguration>();

            // KOLEJNOŚĆ: `Blob:Root` jest w appsettings.json, więc zawsze coś zwraca —
            // postawiony pierwszy zjadałby `BLOB_ROOT` z `.env`.
            var blobRoot = settings["BLOB_ROOT"] ?? settings["Blob:Root"] ?? "data/blob";

            return new DiskBlobStore(RepositoryRoot.Resolve(blobRoot));
        });

        return services;
    }
}
