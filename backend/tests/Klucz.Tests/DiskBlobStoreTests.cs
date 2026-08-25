using System.Text;
using Klucz.Contracts;
using Klucz.Corpus.Infrastructure;

namespace Klucz.Tests;

public class DiskBlobStoreTests : IDisposable
{
    private readonly string _root =
        Path.Combine(Path.GetTempPath(), "klucz-blob-" + Guid.NewGuid().ToString("N"));

    private IBlobStore Store() => new DiskBlobStore(_root);

    public void Dispose()
    {
        if (Directory.Exists(_root))
        {
            Directory.Delete(_root, recursive: true);
        }

        GC.SuppressFinalize(this);
    }

    [Fact]
    public async Task Saved_blob_can_be_read_back_and_is_visible_to_Exists()
    {
        var store = Store();
        var content = "wycinek strony"u8.ToArray();

        var path = await store.SaveAsync("OMAP/2025-05-01/100/X/z16-0.png", new MemoryStream(content));

        Assert.Equal("OMAP/2025-05-01/100/X/z16-0.png", path);
        Assert.True(await store.ExistsAsync(path));

        await using var stream = await store.OpenAsync(path);
        using var reader = new StreamReader(stream, Encoding.UTF8);
        Assert.Equal("wycinek strony", await reader.ReadToEndAsync());
    }

    [Fact]
    public async Task Returned_path_is_relative_and_uses_forward_slashes()
    {
        var path = await Store().SaveAsync("a/b/c.png", new MemoryStream([1, 2, 3]));

        Assert.Equal("a/b/c.png", path);
        Assert.False(Path.IsPathRooted(path));
        Assert.DoesNotContain("\\", path, StringComparison.Ordinal);
    }

    [Fact]
    public async Task Missing_blob_does_not_exist_and_cannot_be_opened()
    {
        var store = Store();

        Assert.False(await store.ExistsAsync("nie/ma/mnie.png"));
        await Assert.ThrowsAsync<FileNotFoundException>(() => store.OpenAsync("nie/ma/mnie.png"));
    }

    [Theory]
    [InlineData("../poza-korzeniem.png")]
    [InlineData("a/../../poza-korzeniem.png")]
    [InlineData("a/b/../../../poza-korzeniem.png")]
    public async Task Escaping_the_root_throws(string path)
    {
        var store = Store();

        await Assert.ThrowsAsync<ArgumentException>(() => store.OpenAsync(path));
        await Assert.ThrowsAsync<ArgumentException>(() => store.SaveAsync(path, new MemoryStream([1])));
        await Assert.ThrowsAsync<ArgumentException>(() => store.ExistsAsync(path));
    }

    [Fact]
    public async Task Absolute_path_throws()
    {
        var absolute = Path.Combine(Path.GetTempPath(), "cudzy-plik.png");

        await Assert.ThrowsAsync<ArgumentException>(() => Store().OpenAsync(absolute));
    }

    [Fact]
    public async Task Sibling_directory_with_similar_name_is_not_inside_the_root()
    {
        await Assert.ThrowsAsync<ArgumentException>(
            () => Store().ExistsAsync("../" + Path.GetFileName(_root) + "-obcy/plik.png"));
    }
}
