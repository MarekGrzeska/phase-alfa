using Klucz.Contracts;
using Klucz.Corpus.Infrastructure;
using Microsoft.Extensions.DependencyInjection;

namespace Klucz.Tests;

public class CompositionTests
{
    [Fact]
    public void Registers_database_probe_and_blob_store()
    {
        using var application = HealthTests.Application([]);
        using var scope = application.Services.CreateScope();

        Assert.NotNull(scope.ServiceProvider.GetRequiredService<IDatabaseProbe>());
        Assert.NotNull(scope.ServiceProvider.GetRequiredService<IBlobStore>());
    }

    [Fact]
    public void BLOB_ROOT_overrides_the_root_from_appsettings()
    {
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
        using var application = HealthTests.Application(new Dictionary<string, string?>
        {
            ["BLOB_ROOT"] = null,
            ["Blob:Root"] = "data/blob",
        });

        var store = Assert.IsType<DiskBlobStore>(application.Services.GetRequiredService<IBlobStore>());

        Assert.Equal(WithSeparator(RepositoryRoot.Resolve("data/blob")), store.Root);
    }

    private static string WithSeparator(string path)
        => Path.TrimEndingDirectorySeparator(path) + Path.DirectorySeparatorChar;
}
