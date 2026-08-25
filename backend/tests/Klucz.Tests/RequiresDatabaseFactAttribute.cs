using Klucz.Corpus.Infrastructure;
using Microsoft.Extensions.Configuration;
using Npgsql;

namespace Klucz.Tests;

/// <summary>
/// Test wymagający żywej bazy — bez niej POMIJANY, z widocznym powodem. Decyduje próba
/// połączenia, nie obecność <c>DB_HOST</c>: Taskfile ma <c>dotenv</c>, więc ta zmienna stoi
/// zawsze, także bez kontenera.
/// </summary>
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

    /// <summary>Sekunda limitu: płaci za nią KAŻDY przebieg testów, także ten bez tego testu.</summary>
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
            // Bez rozróżniania typów: dla decyzji „pomijać czy nie" każdy błąd znaczy to samo.
            return e.Message;
        }
    }
}
