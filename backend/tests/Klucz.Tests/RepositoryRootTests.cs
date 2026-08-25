using Klucz.Corpus.Infrastructure;

namespace Klucz.Tests;

/// <summary>
/// Ścieżki z konfiguracji liczą się od korzenia repozytorium, nie od katalogu procesu.
/// </summary>
public class RepositoryRootTests
{
    [Fact]
    public void Relative_configuration_path_lands_in_the_repository_root()
    {
        // `dotnet run` ustawia katalog roboczy na katalog projektu. Gdyby `data/blob`
        // liczyło się od niego, korpus pisany przez Pythona i czytany przez C# stałby
        // w dwóch różnych miejscach — mimo tej samej wartości w tym samym `.env`.
        var root = RepositoryRoot.Find();
        var resolved = RepositoryRoot.Resolve("data/blob");

        Assert.True(File.Exists(Path.Combine(root, "Taskfile.yml")),
            $"korzeń repozytorium wskazany na {root}, a nie ma tam Taskfile.yml");
        Assert.Equal(Path.Combine(root, "data", "blob"), resolved);
    }

    [Fact]
    public void Absolute_path_is_left_untouched()
    {
        var absolute = Path.Combine(Path.GetTempPath(), "blob");

        Assert.Equal(absolute, RepositoryRoot.Resolve(absolute));
    }
}
