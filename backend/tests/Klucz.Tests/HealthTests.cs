using System.Net;
using System.Net.Http.Json;
using Klucz.Contracts;
using Microsoft.AspNetCore.Mvc.Testing;
using Microsoft.Extensions.Configuration;

namespace Klucz.Tests;

/// <summary>
/// <c>/health</c> ma odpowiadać ZAWSZE i rozdzielać dwa różne zdarzenia: „proces żyje"
/// i „baza odpowiada".
/// </summary>
public class HealthTests
{
    internal static WebApplicationFactory<Program> Application(Dictionary<string, string?> settings)
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
    public async Task Malformed_port_yields_degraded_not_a_500()
    {
        // Literówka w `.env` to BŁĄD KONFIGURACJI, nie awaria API. Wcześniej
        // składanie adresu stało poza `try` w sondzie, więc `FormatException`
        // z `int.Parse(DB_PORT)` wychodziło jako HTTP 500 ze stack trace w treści
        // odpowiedzi: monitoring widział „API leży", choć API stało.
        await using var application = Application(new Dictionary<string, string?>
        {
            ["DB_HOST"] = "127.0.0.1",
            ["DB_PORT"] = "5432x",
            ["DB_NAME"] = "klucz",
            ["DB_USER"] = "klucz",
            ["DB_PASSWORD"] = "nieistotne",
        });

        var response = await application.CreateClient().GetAsync("/health");

        Assert.Equal(HttpStatusCode.OK, response.StatusCode);
        var health = await response.Content.ReadFromJsonAsync<HealthResponse>();
        Assert.Equal("degraded", health!.Status);
        Assert.False(health.Database);
    }

    [Fact]
    public async Task Unsupported_connection_parameter_yields_degraded_not_a_500()
    {
        // Nieznany parametr w `DATABASE_URL` zatrzymuje składanie adresu
        // (`ArgumentException` z buildera Npgsql) — celowo, bo cicha utrata
        // parametru połączenia jest gorsza niż błąd. Ale endpoint ma to oddać
        // jako `degraded`, a nie jako 500.
        await using var application = Application(new Dictionary<string, string?>
        {
            ["DATABASE_URL"] = "postgresql://klucz:tajne@localhost:5432/klucz?takiego_parametru_nie_ma=1",
        });

        var response = await application.CreateClient().GetAsync("/health");

        Assert.Equal(HttpStatusCode.OK, response.StatusCode);
        var health = await response.Content.ReadFromJsonAsync<HealthResponse>();
        Assert.Equal("degraded", health!.Status);
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

        // Komunikat opisuje to, co WIDAĆ, a nie to, co powinno być prawdą. Wcześniej
        // stało tu „baza stoi (`task up`), a health check jej nie widzi" — zdanie
        // twierdzące odwrotność stanu faktycznego, gdy kontenera po prostu nie było.
        // Od czasu, gdy atrybut pomija test po nieudanej próbie połączenia, ta asercja
        // zapala się tylko wtedy, gdy baza ODPOWIADA, a API jej mimo to nie widzi —
        // czyli gdy zepsuta jest konfiguracja API, nie baza.
        var target = $"{Environment.GetEnvironmentVariable("DB_HOST")}:{Environment.GetEnvironmentVariable("DB_PORT")}";

        Assert.NotNull(health);
        Assert.True(health!.Database,
            $"baza pod {target} odpowiada, ale API jej nie widzi — sprawdź konfigurację API, nie kontener");
        Assert.Equal("ok", health.Status);
    }
}
