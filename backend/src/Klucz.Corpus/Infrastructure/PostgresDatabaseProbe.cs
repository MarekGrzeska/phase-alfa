using Klucz.Contracts;
using Microsoft.Extensions.Configuration;
using Microsoft.Extensions.Logging;
using Npgsql;

namespace Klucz.Corpus.Infrastructure;

/// <summary>
/// Ping do bazy przez <c>SELECT 1</c>. Jedyne miejsce w backendzie, które trzyma Npgsql w ręku.
/// Powód awarii idzie do logu, nie do odpowiedzi HTTP.
/// </summary>
public sealed class PostgresDatabaseProbe(IConfiguration configuration, ILogger<PostgresDatabaseProbe> log)
    : IDatabaseProbe
{
    // Leniwie, bo OpenAPI powstaje przy buildzie i generator startuje w tym celu aplikację —
    // sprawdzanie zmiennych w `AddCorpus` znaczyłoby, że `dotnet build` wymaga bazy.
    private readonly Lazy<string> _connectionString = new(
        () => DatabaseConnectionString.FromEnvironment(configuration),
        // NIE ExecutionAndPublication: ten zapamiętuje też WYJĄTEK, aż do restartu procesu.
        LazyThreadSafetyMode.PublicationOnly);

    public async Task<bool> IsAliveAsync(CancellationToken ct = default)
    {
        try
        {
            // Odczyt adresu W ŚRODKU `try`: czyta konfigurację i potrafi rzucić, a wtedy zła
            // konfiguracja wychodzi jako HTTP 500 i monitoring widzi „API leży".
            var connectionString = _connectionString.Value;

            await using var connection = new NpgsqlConnection(connectionString);
            await connection.OpenAsync(ct);
            await using var command = new NpgsqlCommand("SELECT 1", connection);
            await command.ExecuteScalarAsync(ct);
            return true;
        }
        catch (Exception e) when (e is NpgsqlException or TimeoutException
                                    or InvalidOperationException or FormatException
                                    or ArgumentException)
        {
            log.LogWarning(e, "Baza nie odpowiedziała na ping");
            return false;
        }
    }
}
