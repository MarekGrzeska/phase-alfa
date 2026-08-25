using System.Net;
using System.Net.Http.Json;
using Klucz.Contracts;
using Microsoft.AspNetCore.Mvc.Testing;
using Microsoft.Extensions.Configuration;
using Microsoft.Extensions.DependencyInjection;

namespace Klucz.Tests;

/// <summary>
/// <c>/health</c> ma odpowiadać ZAWSZE i rozdzielać dwa różne zdarzenia: „proces żyje"
/// i „baza odpowiada".
/// </summary>
public class HealthTests
{
    private static WebApplicationFactory<Program> Application(Dictionary<string, string?> settings)
        => new WebApplicationFactory<Program>().WithWebHostBuilder(builder =>
            builder.ConfigureAppConfiguration((_, config) => config.AddInMemoryCollection(settings)));

    [Fact]
    public async Task Unreachable_database_yields_degraded_not_an_error()
    {
        // Port 1 na pętli zwrotnej odmawia połączenia natychmiast — to jest
        // „baza leży", a nie „baza wolno odpowiada".
        await using var application = Application(new Dictionary<string, string?>
        {
            ["DB_HOST"] = "127.0.0.1",
            ["DB_PORT"] = "1",
            ["DB_NAME"] = "klucz",
            ["DB_USER"] = "klucz",
            ["DB_PASSWORD"] = "nieistotne",
        });

        var response = await application.CreateClient().GetAsync("/health");

        Assert.Equal(HttpStatusCode.OK, response.StatusCode);
        var health = await response.Content.ReadFromJsonAsync<HealthResponse>();
        Assert.NotNull(health);
        Assert.False(health!.Database);
        Assert.Equal("degraded", health.Status);
    }

    [Fact]
    public async Task Missing_database_configuration_does_not_break_startup()
    {
        // Build generuje dokument OpenAPI, a żeby go wygenerować, startuje aplikację.
        // Gdyby brak zmiennych przewracał start, `dotnet build` wymagałby Postgresa.
        await using var application = Application(new Dictionary<string, string?>
        {
            ["DB_HOST"] = null,
            ["DB_PORT"] = null,
            ["DB_NAME"] = null,
            ["DB_USER"] = null,
            ["DB_PASSWORD"] = null,
            ["DATABASE_URL"] = null,
        });

        var response = await application.CreateClient().GetAsync("/health");
        var health = await response.Content.ReadFromJsonAsync<HealthResponse>();

        Assert.Equal(HttpStatusCode.OK, response.StatusCode);
        Assert.False(health!.Database);
    }

    [RequiresDatabaseFact]
    public async Task Live_database_yields_ok()
    {
        await using var application = new WebApplicationFactory<Program>();

        var health = await application.CreateClient().GetFromJsonAsync<HealthResponse>("/health");

        Assert.NotNull(health);
        Assert.True(health!.Database, "baza stoi (`task up`), a health check jej nie widzi");
        Assert.Equal("ok", health.Status);
    }

    [Fact]
    public void Composition_registers_database_probe_and_blob_store()
    {
        // Kompozycja jest częścią umowy: moduły rejestrują porty, Api ich używa.
        // Gdyby rejestracja zniknęła, `/health` przewróciłby się dopiero w czasie
        // żądania — a to jest błąd, który chce się widzieć przy starcie.
        using var application = Application([]);
        using var scope = application.Services.CreateScope();

        Assert.NotNull(scope.ServiceProvider.GetRequiredService<IDatabaseProbe>());
        Assert.NotNull(scope.ServiceProvider.GetRequiredService<IBlobStore>());
    }
}
