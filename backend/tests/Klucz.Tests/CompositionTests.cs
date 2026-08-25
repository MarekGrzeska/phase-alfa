using Klucz.Contracts;
using Klucz.Corpus.Infrastructure;
using Microsoft.Extensions.DependencyInjection;

namespace Klucz.Tests;

/// <summary>
/// Kompozycja: co `Program.cs` dostaje z modułów i JAK to zostało skonfigurowane.
/// </summary>
/// <remarks>
/// Samo „usługa się zarejestrowała" to za mało. Test, który sprawdza wyłącznie
/// obecność <c>IBlobStore</c> w kontenerze, przechodzi niezależnie od tego, na co
/// wskazuje korzeń składu — czyli także wtedy, gdy <c>BLOB_ROOT</c> z <c>.env</c>
/// jest po cichu ignorowane, a Python i C# piszą w dwóch różnych miejscach.
/// </remarks>
public class CompositionTests
{
    [Fact]
    public void Registers_database_probe_and_blob_store()
    {
        // Kompozycja jest częścią umowy: moduły rejestrują porty, Api ich używa.
        // Gdyby rejestracja zniknęła, `/health` przewróciłby się dopiero w czasie
        // żądania — a to jest błąd, który chce się widzieć przy starcie.
        using var application = HealthTests.Application([]);
        using var scope = application.Services.CreateScope();

        Assert.NotNull(scope.ServiceProvider.GetRequiredService<IDatabaseProbe>());
        Assert.NotNull(scope.ServiceProvider.GetRequiredService<IBlobStore>());
    }

    [Fact]
    public void BLOB_ROOT_overrides_the_root_from_appsettings()
    {
        // `Blob:Root` stoi w appsettings.json, więc ZAWSZE coś zwraca. Postawiony
        // przed `BLOB_ROOT` w alternatywie `??` zjadał go w całości i zmienna ze
        // środowiska nie wykonywała się nigdy — mimo że `.env.example`
        // i `backend/README.md` obiecują, że to nią przenosi się skład.
        using var application = HealthTests.Application(new Dictionary<string, string?>
        {
            ["BLOB_ROOT"] = "data/blob-z-env",
        });

        var store = Assert.IsType<DiskBlobStore>(application.Services.GetRequiredService<IBlobStore>());

        Assert.Equal(WithSeparator(RepositoryRoot.Resolve("data/blob-z-env")), store.Root);
    }

    [Fact]
    public void Without_BLOB_ROOT_the_root_comes_from_appsettings()
    {
        // Druga strona tej samej alternatywy: bez zmiennej środowiskowej korzeń
        // ma stać tam, gdzie mówi konfiguracja pliku — i liczyć się od korzenia
        // repozytorium, nie od katalogu roboczego procesu.
        using var application = HealthTests.Application(new Dictionary<string, string?>
        {
            ["BLOB_ROOT"] = null,
            ["Blob:Root"] = "data/blob",
        });

        var store = Assert.IsType<DiskBlobStore>(application.Services.GetRequiredService<IBlobStore>());

        Assert.Equal(WithSeparator(RepositoryRoot.Resolve("data/blob")), store.Root);
    }

    /// <summary>Korzeń składu trzyma na końcu separator — bez niego `blob-obcy` mieściłby się w `blob`.</summary>
    private static string WithSeparator(string path)
        => Path.TrimEndingDirectorySeparator(path) + Path.DirectorySeparatorChar;
}
