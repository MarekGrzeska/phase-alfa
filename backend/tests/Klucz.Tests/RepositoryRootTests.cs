using Klucz.Corpus.Infrastructure;

namespace Klucz.Tests;

public class RepositoryRootTests
{
    [Fact]
    public void Relative_configuration_path_lands_in_the_repository_root()
    {
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
