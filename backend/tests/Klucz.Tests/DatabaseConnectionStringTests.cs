using Klucz.Corpus.Infrastructure;
using Microsoft.Extensions.Configuration;
using Npgsql;

namespace Klucz.Tests;

/// <summary>
/// Składanie adresu bazy z konfiguracji — ścieżka, która wcześniej nie miała ani jednego testu.
/// </summary>
/// <remarks>
/// Najdroższy błąd tej klasy nie wywala się głośno: <c>sslmode=require</c> zjadane
/// po cichu zostawia Npgsql przy domyślnym <c>Prefer</c>, czyli zgadza się na
/// połączenie NIESZYFROWANE, gdy serwer tak powie. A <c>DATABASE_URL</c> z definicji
/// wskazuje bazę inną niż deweloperska — zwykle zdalną.
/// </remarks>
public class DatabaseConnectionStringTests
{
    private static IConfiguration Configuration(Dictionary<string, string?> values)
        => new ConfigurationBuilder().AddInMemoryCollection(values).Build();

    [Fact]
    public void Url_keeps_sslmode_from_the_query_string()
    {
        var connectionString = DatabaseConnectionString.FromUrl(
            "postgresql://klucz:tajne@db.example.com:5432/klucz?sslmode=require");

        var parsed = new NpgsqlConnectionStringBuilder(connectionString);

        Assert.Equal(SslMode.Require, parsed.SslMode);
        Assert.Equal("db.example.com", parsed.Host);
        Assert.Equal(5432, parsed.Port);
        Assert.Equal("klucz", parsed.Database);
        Assert.Equal("klucz", parsed.Username);
        Assert.Equal("tajne", parsed.Password);
    }

    [Fact]
    public void Url_without_query_string_still_works()
    {
        var parsed = new NpgsqlConnectionStringBuilder(
            DatabaseConnectionString.FromUrl("postgresql://klucz:tajne@localhost:55434/klucz"));

        Assert.Equal("localhost", parsed.Host);
        Assert.Equal(55434, parsed.Port);
        Assert.Equal("klucz", parsed.Database);
    }

    [Fact]
    public void Unsupported_connection_parameter_is_rejected_not_swallowed()
    {
        // Głośny błąd konfiguracji jest lepszy niż ciche zjedzenie parametru,
        // o którym ktoś myśli, że działa. Sondę bazy to nie przewraca —
        // `ArgumentException` jest w jej filtrze i wychodzi jako `degraded`.
        Assert.Throws<ArgumentException>(() => DatabaseConnectionString.FromUrl(
            "postgresql://klucz:tajne@localhost:5432/klucz?takiego_parametru_nie_ma=1"));
    }

    [Fact]
    public void Port_that_is_not_a_number_names_the_variable()
    {
        // `int.Parse` mówił „The input string '5432x' was not in a correct format"
        // i nie zdradzał, KTÓRA z pięciu zmiennych jest zła.
        var error = Assert.Throws<FormatException>(() => DatabaseConnectionString.FromEnvironment(
            Configuration(new Dictionary<string, string?>
            {
                ["DB_HOST"] = "localhost",
                ["DB_PORT"] = "5432x",
                ["DB_NAME"] = "klucz",
                ["DB_USER"] = "klucz",
                ["DB_PASSWORD"] = "klucz_dev",
            })));

        Assert.Contains("DB_PORT", error.Message, StringComparison.Ordinal);
        Assert.Contains("5432x", error.Message, StringComparison.Ordinal);
    }

    [Fact]
    public void Missing_variables_are_listed_by_name()
    {
        var error = Assert.Throws<InvalidOperationException>(() => DatabaseConnectionString.FromEnvironment(
            Configuration(new Dictionary<string, string?> { ["DB_HOST"] = "localhost" })));

        Assert.Contains("DB_PORT", error.Message, StringComparison.Ordinal);
        Assert.Contains("DB_PASSWORD", error.Message, StringComparison.Ordinal);
        Assert.DoesNotContain("DB_HOST", error.Message, StringComparison.Ordinal);
    }

    [Fact]
    public void DATABASE_URL_wins_over_the_parts()
    {
        var connectionString = DatabaseConnectionString.FromEnvironment(
            Configuration(new Dictionary<string, string?>
            {
                ["DATABASE_URL"] = "postgresql://inny:haslo@zdalna:5432/inna",
                ["DB_HOST"] = "localhost",
                ["DB_PORT"] = "55434",
                ["DB_NAME"] = "klucz",
                ["DB_USER"] = "klucz",
                ["DB_PASSWORD"] = "klucz_dev",
            }));

        Assert.Equal("zdalna", new NpgsqlConnectionStringBuilder(connectionString).Host);
    }
}
