using Microsoft.Extensions.Configuration;
using Npgsql;

namespace Klucz.Corpus.Infrastructure;

/// <summary>
/// Adres bazy — wyłącznie z konfiguracji, nigdy z kodu.
/// </summary>
/// <remarks>
/// Ta sama reguła co w <c>ingest/schema/migrate.py</c>: adres SKŁADANY z części
/// (<c>DB_HOST</c>, <c>DB_PORT</c>, …), a nie wpisany w całości. Numer portu stał
/// wcześniej w <c>.env</c> dwa razy — raz dla Dockera, raz w gotowym adresie — i przy
/// kolizji portów zmieniało się jedno z nich, a objaw („baza nieosiągalna") nie
/// wskazywał na przyczynę.
///
/// <c>DATABASE_URL</c> ma pierwszeństwo i służy do wskazania innej bazy niż
/// deweloperska. Npgsql nie czyta adresów w formie <c>postgresql://</c>, więc
/// rozkładamy je tutaj na części — inaczej ten sam <c>.env</c> działałby dla Pythona
/// i nie działał dla C#.
/// </remarks>
public static class DatabaseConnectionString
{
    private static readonly string[] RequiredKeys =
        ["DB_HOST", "DB_PORT", "DB_NAME", "DB_USER", "DB_PASSWORD"];

    public static string FromEnvironment(IConfiguration configuration)
    {
        var url = configuration["DATABASE_URL"];
        if (!string.IsNullOrWhiteSpace(url))
        {
            return FromUrl(url);
        }

        var missing = RequiredKeys.Where(key => string.IsNullOrWhiteSpace(configuration[key])).ToArray();
        if (missing.Length > 0)
        {
            throw new InvalidOperationException(
                $"BRAK zmiennych: {string.Join(", ", missing)}. " +
                "Skopiuj .env.example do .env (albo ustaw je w środowisku).");
        }

        return new NpgsqlConnectionStringBuilder
        {
            Host = configuration["DB_HOST"],
            Port = int.Parse(configuration["DB_PORT"]!),
            Database = configuration["DB_NAME"],
            Username = configuration["DB_USER"],
            Password = configuration["DB_PASSWORD"],
        }.ConnectionString;
    }

    /// <summary>`postgresql://user:haslo@host:port/baza` → format, który rozumie Npgsql.</summary>
    public static string FromUrl(string url)
    {
        var uri = new Uri(url);
        var credentials = uri.UserInfo.Split(':', 2);

        return new NpgsqlConnectionStringBuilder
        {
            Host = uri.Host,
            Port = uri.IsDefaultPort ? 5432 : uri.Port,
            Database = uri.AbsolutePath.TrimStart('/'),
            Username = Uri.UnescapeDataString(credentials[0]),
            Password = credentials.Length > 1 ? Uri.UnescapeDataString(credentials[1]) : null,
        }.ConnectionString;
    }
}
