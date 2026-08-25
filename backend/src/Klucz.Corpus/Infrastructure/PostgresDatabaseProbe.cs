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
/// <c>AddCorpus</c> znaczyłoby, że `dotnet build` wymaga bazy — czyli że nie da się
/// zbudować projektu bez postawionego Postgresa.
///
/// Zwraca fałsz zamiast rzucać, bo health check ma odpowiedzieć ZAWSZE — odpowiedź
/// „proces żyje, baza nie" jest właśnie tą, po którą się do niego przychodzi.
/// Powód awarii idzie do logu, nie do odpowiedzi HTTP: adres bazy i nazwa użytkownika
/// nie są rzeczami, które wystawia się bez pytania.
/// </remarks>
public sealed class PostgresDatabaseProbe(IConfiguration konfiguracja, ILogger<PostgresDatabaseProbe> log)
    : IDatabaseProbe
{
    private readonly Lazy<string> _adres =
        new(() => PolaczenieBazy.ZeSrodowiska(konfiguracja), LazyThreadSafetyMode.ExecutionAndPublication);

    public async Task<bool> OdpowiadaAsync(CancellationToken ct = default)
    {
        try
        {
            await using var polaczenie = new NpgsqlConnection(_adres.Value);
            await polaczenie.OpenAsync(ct);
            await using var polecenie = new NpgsqlCommand("SELECT 1", polaczenie);
            await polecenie.ExecuteScalarAsync(ct);
            return true;
        }
        catch (Exception e) when (e is NpgsqlException or TimeoutException or InvalidOperationException)
        {
            log.LogWarning(e, "Baza nie odpowiedziała na ping");
            return false;
        }
    }
}
