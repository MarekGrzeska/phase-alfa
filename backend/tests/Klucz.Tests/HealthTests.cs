using System.Net;
using System.Net.Http.Json;
using Klucz.Contracts;
using Microsoft.AspNetCore.Mvc.Testing;
using Microsoft.Extensions.Configuration;

namespace Klucz.Tests;

public class HealthTests
{
    internal static WebApplicationFactory<Program> Application(Dictionary<string, string?> settings)
        => new WebApplicationFactory<Program>().WithWebHostBuilder(builder =>
            builder.ConfigureAppConfiguration((_, config) => config.AddInMemoryCollection(settings)));

    [Fact]
    public async Task Unreachable_database_yields_degraded_not_an_error()
    {
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

        var target = $"{Environment.GetEnvironmentVariable("DB_HOST")}:{Environment.GetEnvironmentVariable("DB_PORT")}";

        Assert.NotNull(health);
        Assert.True(health!.Database,
            $"baza pod {target} odpowiada, ale API jej nie widzi — sprawdź konfigurację API, nie kontener");
        Assert.Equal("ok", health.Status);
    }
}
