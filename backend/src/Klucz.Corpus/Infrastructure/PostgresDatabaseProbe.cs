using Klucz.Contracts;
using Microsoft.Extensions.Configuration;
using Microsoft.Extensions.Logging;
using Npgsql;

namespace Klucz.Corpus.Infrastructure;

/// <summary>
/// Ping do bazy przez <c>SELECT 1</c>. Jedyne miejsce w backendzie, które trzyma Npgsql w ręku.
/// </summary>
/// <remarks>
/// Adres jest rozwiązywany LENIWIE, przy pierwszym pytaniu — nie przy rejestracji usług.
/// Powód jest konkretny: dokument OpenAPI powstaje przy buildzie, a generator startuje
/// w tym celu całą aplikację. Sprawdzanie zmiennych środowiskowych w
/// <c>AddCorpus</c> znaczyłoby, że <c>dotnet build</c> wymaga bazy — czyli że nie da się
/// zbudować projektu bez postawionego Postgresa.
///
/// Zwraca fałsz zamiast rzucać, bo health check ma odpowiedzieć ZAWSZE — odpowiedź
/// „proces żyje, baza nie" jest właśnie tą, po którą się do niego przychodzi.
/// Powód awarii idzie do logu, nie do odpowiedzi HTTP: adres bazy i nazwa użytkownika
/// nie są rzeczami, które wystawia się bez pytania.
/// </remarks>
public sealed class PostgresDatabaseProbe(IConfiguration configuration, ILogger<PostgresDatabaseProbe> log)
    : IDatabaseProbe
{
    private readonly Lazy<string> _connectionString = new(
        () => DatabaseConnectionString.FromEnvironment(configuration),
        // PublicationOnly, NIE ExecutionAndPublication: ten drugi zapamiętuje także
        // WYJĄTEK i oddaje go przy każdym kolejnym odczycie aż do restartu procesu.
        // Literówka w konfiguracji zostawałaby więc w pamięci również po jej
        // poprawieniu i przeładowaniu konfiguracji. Fabryka jest czysta (składa
        // napis), więc jej ewentualne dwukrotne wykonanie nic nie kosztuje.
        LazyThreadSafetyMode.PublicationOnly);

    public async Task<bool> IsAliveAsync(CancellationToken ct = default)
    {
        try
        {
            // Odczyt adresu jest W ŚRODKU `try`, bo składanie go czyta konfigurację
            // i potrafi rzucić: zły `DB_PORT` (FormatException), popsuty
            // `DATABASE_URL` (UriFormatException — pochodna FormatException),
            // nieznany parametr połączenia (ArgumentException), brak zmiennych
            // (InvalidOperationException). Poza `try` ten sam błąd wychodził
            // z endpointu jako HTTP 500 ze stack trace w treści odpowiedzi —
            // czyli monitoring widział „API leży", choć API stało i zła była
            // wyłącznie konfiguracja. To łamało wprost kontrakt `IDatabaseProbe`
            // („Nie rzuca — zwraca fałsz").
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
