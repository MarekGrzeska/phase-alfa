using System.Text;
using Klucz.Contracts;
using Klucz.Corpus.Infrastructure;

namespace Klucz.Tests;

/// <summary>
/// Skład blobów: zapis, odczyt i — najważniejsze — brak drogi na zewnątrz korzenia.
/// </summary>
/// <remarks>
/// `..` w nazwie pliku nie jest scenariuszem z bajki, gdy nazwy biorą się z tekstu
/// PDF-a. Te testy są tanie, a pilnują jedynej granicy, jaką ma ten skład.
/// </remarks>
public class DyskowyBlobStoreTests : IDisposable
{
    private readonly string _korzen =
        Path.Combine(Path.GetTempPath(), "klucz-blob-" + Guid.NewGuid().ToString("N"));

    private IBlobStore Skład() => new DyskowyBlobStore(_korzen);

    public void Dispose()
    {
        if (Directory.Exists(_korzen))
        {
            Directory.Delete(_korzen, recursive: true);
        }

        GC.SuppressFinalize(this);
    }

    [Fact]
    public async Task Zapisany_plik_daje_sie_odczytac_i_widac_go_przez_Istnieje()
    {
        var skład = Skład();
        var tresc = "wycinek strony"u8.ToArray();

        var sciezka = await skład.ZapiszAsync("OMAP/2025-05-01/100/X/z16-0.png", new MemoryStream(tresc));

        Assert.Equal("OMAP/2025-05-01/100/X/z16-0.png", sciezka);
        Assert.True(await skład.IstniejeAsync(sciezka));

        await using var strumien = await skład.OtworzAsync(sciezka);
        using var czytnik = new StreamReader(strumien, Encoding.UTF8);
        Assert.Equal("wycinek strony", await czytnik.ReadToEndAsync());
    }

    [Fact]
    public async Task Zwracana_sciezka_jest_wzgledna_i_z_ukosnikiem_w_przod()
    {
        // W bazie stoją ścieżki względne — absolutna albo z literą dysku zabija
        // przenośność korpusu między maszynami, a separator w tył zabija ją
        // między systemami.
        var sciezka = await Skład().ZapiszAsync("a/b/c.png", new MemoryStream([1, 2, 3]));

        Assert.Equal("a/b/c.png", sciezka);
        Assert.False(Path.IsPathRooted(sciezka));
        Assert.DoesNotContain("\\", sciezka, StringComparison.Ordinal);
    }

    [Fact]
    public async Task Nieistniejacy_plik_nie_istnieje_i_nie_daje_sie_otworzyc()
    {
        var skład = Skład();

        Assert.False(await skład.IstniejeAsync("nie/ma/mnie.png"));
        await Assert.ThrowsAsync<FileNotFoundException>(() => skład.OtworzAsync("nie/ma/mnie.png"));
    }

    [Theory]
    [InlineData("../poza-korzeniem.png")]
    [InlineData("a/../../poza-korzeniem.png")]
    [InlineData("a/b/../../../poza-korzeniem.png")]
    public async Task Wyjscie_poza_korzen_rzuca(string sciezka)
    {
        var skład = Skład();

        await Assert.ThrowsAsync<ArgumentException>(() => skład.OtworzAsync(sciezka));
        await Assert.ThrowsAsync<ArgumentException>(
            () => skład.ZapiszAsync(sciezka, new MemoryStream([1])));
        await Assert.ThrowsAsync<ArgumentException>(() => skład.IstniejeAsync(sciezka));
    }

    [Fact]
    public async Task Sciezka_absolutna_rzuca()
    {
        var absolutna = Path.Combine(Path.GetTempPath(), "cudzy-plik.png");

        await Assert.ThrowsAsync<ArgumentException>(() => Skład().OtworzAsync(absolutna));
    }

    [Fact]
    public async Task Katalog_obok_korzenia_o_podobnej_nazwie_nie_liczy_sie_jako_wnetrze()
    {
        // `/data/blob-obcy` zaczyna się tak samo jak `/data/blob`. Bez separatora
        // na końcu korzenia porównanie prefiksem przepuszczałoby cudzy katalog.
        await Assert.ThrowsAsync<ArgumentException>(
            () => Skład().IstniejeAsync("../" + Path.GetFileName(_korzen) + "-obcy/plik.png"));
    }
}
