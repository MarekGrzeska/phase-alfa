using Microsoft.Extensions.Configuration;
using Npgsql;

namespace Klucz.Corpus.Infrastructure;

/// <summary>
/// Adres bazy SKŁADANY z części, tak samo jak w <c>ingest/schema/migrate.py</c>. Błędy tej klasy
/// łapie <see cref="PostgresDatabaseProbe"/>, więc rzucamy typami, które zna jego filtr.
/// </summary>
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

        // TryParse, bo `int.Parse` nie zdradza, KTÓRA z pięciu zmiennych jest zła.
        var portText = configuration["DB_PORT"]!;
        if (!int.TryParse(portText, out var port))
        {
            throw new FormatException($"DB_PORT ma być liczbą, a jest „{portText}”. Popraw .env.");
        }

        return new NpgsqlConnectionStringBuilder
        {
            Host = configuration["DB_HOST"],
            Port = port,
            Database = configuration["DB_NAME"],
            Username = configuration["DB_USER"],
            Password = configuration["DB_PASSWORD"],
        }.ConnectionString;
    }

    /// <summary>
    /// `postgresql://…` → format Npgsql. Parametry z query stringa PRZEPISUJEMY: bez
    /// <c>sslmode</c> Npgsql zostaje przy <c>Prefer</c>, czyli godzi się na połączenie
    /// nieszyfrowane ze zdalną bazą.
    /// </summary>
    public static string FromUrl(string url)
    {
        var uri = new Uri(url);
        var credentials = uri.UserInfo.Split(':', 2);

        var builder = new NpgsqlConnectionStringBuilder
        {
            Host = uri.Host,
            Port = uri.IsDefaultPort ? 5432 : uri.Port,
            Database = uri.AbsolutePath.TrimStart('/'),
            Username = Uri.UnescapeDataString(credentials[0]),
            Password = credentials.Length > 1 ? Uri.UnescapeDataString(credentials[1]) : null,
        };

        foreach (var (key, value) in ParseQuery(uri.Query))
        {
            builder[key] = value;
        }

        return builder.ConnectionString;
    }

    private static List<(string Key, string Value)> ParseQuery(string query)
    {
        var pairs = new List<(string, string)>();

        foreach (var part in query.TrimStart('?').Split('&', StringSplitOptions.RemoveEmptyEntries))
        {
            var separator = part.IndexOf('=', StringComparison.Ordinal);
            if (separator < 0)
            {
                throw new ArgumentException(
                    $"Parametr bez wartości w DATABASE_URL: „{part}”.", nameof(query));
            }

            pairs.Add((Uri.UnescapeDataString(part[..separator]),
                       Uri.UnescapeDataString(part[(separator + 1)..])));
        }

        return pairs;
    }
}
