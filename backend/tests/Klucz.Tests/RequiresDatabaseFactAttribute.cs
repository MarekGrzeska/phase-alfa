using Klucz.Corpus.Infrastructure;
using Microsoft.Extensions.Configuration;
using Npgsql;

namespace Klucz.Tests;

/// <summary>
/// Test wymagający żywej bazy. Bez niej POMIJANY — z widocznym powodem.
/// </summary>
/// <remarks>
/// Pominięcie musi być widać w wyniku przebiegu. Test, który po cichu przechodzi,
/// bo bazy nie było, jest nieodróżnialny od testu, który nic nie sprawdza
/// (CLAUDE.md). W CI baza stoi, więc tam ten test ma się wykonać naprawdę.
///
/// Decyduje PRÓBA POŁĄCZENIA, nie obecność zmiennej środowiskowej. Sprawdzanie
/// samego <c>DB_HOST</c> nie pomijało nigdy: <c>Taskfile.yml</c> ma
/// <c>dotenv: ['.env']</c>, więc pod <c>task test</c> ta zmienna jest ustawiona
/// zawsze — także wtedy, gdy kontenera z bazą nie ma. Deweloper, który zapomniał
/// <c>task up</c>, dostawał wtedy CZERWONY test z komunikatem twierdzącym dokładną
/// odwrotność stanu faktycznego i zaczynał szukać błędu w health checku, który był
/// sprawny.
/// </remarks>
public sealed class RequiresDatabaseFactAttribute : FactAttribute
{
    public RequiresDatabaseFactAttribute()
    {
        var failure = ConnectionFailure();
        if (failure is not null)
        {
            Skip = $"baza nie odpowiada — uruchom `task up` ({failure})";
        }
    }

    /// <summary>Powód, dla którego baza jest nieosiągalna — albo <c>null</c>, gdy odpowiada.</summary>
    /// <remarks>
    /// Adres składamy tym samym kodem co produkt (<see cref="DatabaseConnectionString"/>),
    /// więc literówka w <c>.env</c> daje tu ten sam komunikat, co w logu API.
    ///
    /// Sekunda limitu, bo to jest pytanie „czy stoi", a nie czekanie na start bazy —
    /// a płaci za nie KAŻDY przebieg testów, także ten, który tego testu nie uruchamia
    /// (atrybuty czytane są przy wykrywaniu testów).
    /// </remarks>
    private static string? ConnectionFailure()
    {
        try
        {
            var configuration = new ConfigurationBuilder().AddEnvironmentVariables().Build();

            var connectionString = new NpgsqlConnectionStringBuilder(
                DatabaseConnectionString.FromEnvironment(configuration))
            {
                Timeout = 1,
                CommandTimeout = 1,
            }.ConnectionString;

            using var connection = new NpgsqlConnection(connectionString);
            connection.Open();
            return null;
        }
        catch (Exception e)
        {
            // Bez rozróżniania typów: dla decyzji „pomijać czy nie" każdy błąd znaczy
            // to samo — bazy tu nie ma. Komunikat idzie do powodu pominięcia, żeby
            // było widać, CZY to brak kontenera, czy zła konfiguracja.
            return e.Message;
        }
    }
}
