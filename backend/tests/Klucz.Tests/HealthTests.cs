using System.Net;
using System.Net.Http.Json;
using Klucz.Contracts;
using Microsoft.AspNetCore.Mvc.Testing;
using Microsoft.Extensions.Configuration;
using Microsoft.Extensions.DependencyInjection;

namespace Klucz.Tests;

/// <summary>
/// `/health` ma odpowiadać ZAWSZE i rozdzielać dwa różne zdarzenia: „proces żyje"
/// i „baza odpowiada".
/// </summary>
public class HealthTests
{
    private static WebApplicationFactory<Program> Aplikacja(Dictionary<string, string?> ustawienia)
        => new WebApplicationFactory<Program>().WithWebHostBuilder(builder =>
        {
            builder.ConfigureAppConfiguration((_, cfg) => cfg.AddInMemoryCollection(ustawienia));
        });

    [Fact]
    public async Task Nieosiagalna_baza_daje_odpowiedz_degraded_a_nie_blad()
    {
        // Port 1 na pętli zwrotnej odmawia połączenia natychmiast — to jest
        // „baza leży", a nie „baza wolno odpowiada".
        await using var aplikacja = Aplikacja(new Dictionary<string, string?>
        {
            ["DB_HOST"] = "127.0.0.1",
            ["DB_PORT"] = "1",
            ["DB_NAME"] = "klucz",
            ["DB_USER"] = "klucz",
            ["DB_PASSWORD"] = "nieistotne",
        });

        var odpowiedz = await aplikacja.CreateClient().GetAsync("/health");

        Assert.Equal(HttpStatusCode.OK, odpowiedz.StatusCode);
        var stan = await odpowiedz.Content.ReadFromJsonAsync<HealthResponse>();
        Assert.NotNull(stan);
        Assert.False(stan!.Database);
        Assert.Equal("degraded", stan.Status);
    }

    [Fact]
    public async Task Brak_konfiguracji_bazy_nie_wywala_aplikacji()
    {
        // Build generuje dokument OpenAPI, a żeby go wygenerować, startuje aplikację.
        // Gdyby brak zmiennych przewracał start, `dotnet build` wymagałby Postgresa.
        await using var aplikacja = Aplikacja(new Dictionary<string, string?>
        {
            ["DB_HOST"] = null,
            ["DB_PORT"] = null,
            ["DB_NAME"] = null,
            ["DB_USER"] = null,
            ["DB_PASSWORD"] = null,
            ["DATABASE_URL"] = null,
        });

        var odpowiedz = await aplikacja.CreateClient().GetAsync("/health");
        var stan = await odpowiedz.Content.ReadFromJsonAsync<HealthResponse>();

        Assert.Equal(HttpStatusCode.OK, odpowiedz.StatusCode);
        Assert.False(stan!.Database);
    }

    [FaktZBaza]
    public async Task Zywa_baza_daje_odpowiedz_ok()
    {
        await using var aplikacja = new WebApplicationFactory<Program>();

        var stan = await aplikacja.CreateClient().GetFromJsonAsync<HealthResponse>("/health");

        Assert.NotNull(stan);
        Assert.True(stan!.Database, "baza stoi (`task up`), a health check jej nie widzi");
        Assert.Equal("ok", stan.Status);
    }

    [Fact]
    public void Kontrakt_ma_jeden_port_bazy_i_jeden_blob_store()
    {
        // Kompozycja jest częścią umowy: moduły rejestrują porty, Api ich używa.
        // Gdyby rejestracja zniknęła, `/health` przewróciłby się dopiero w czasie
        // żądania — a to jest błąd, który chce się widzieć przy starcie.
        using var aplikacja = Aplikacja([]);
        using var zakres = aplikacja.Services.CreateScope();

        Assert.NotNull(zakres.ServiceProvider.GetRequiredService<IDatabaseProbe>());
        Assert.NotNull(zakres.ServiceProvider.GetRequiredService<IBlobStore>());
    }
}
