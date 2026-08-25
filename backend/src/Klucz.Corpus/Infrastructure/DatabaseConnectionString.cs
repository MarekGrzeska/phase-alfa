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
///
/// Wszystkie błędy tej klasy (brak zmiennych, zły port, popsuty adres) są łapane
/// przez <see cref="PostgresDatabaseProbe"/> i zamieniane na <c>degraded</c>.
/// Rzucamy typami, które ten filtr zna: <see cref="InvalidOperationException"/>,
/// <see cref="FormatException"/>, <see cref="ArgumentException"/>.
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

        // TryParse, a nie Parse: komunikat `FormatException` z `int.Parse` brzmi
        // „The input string '5432x' was not in a correct format" i nie mówi, KTÓRA
        // zmienna jest zła. Przy pięciu zmiennych to jest różnica między poprawką
        // w minutę a szukaniem po omacku.
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

    /// <summary>`postgresql://user:haslo@host:port/baza?sslmode=require` → format, który rozumie Npgsql.</summary>
    /// <remarks>
    /// Parametry z query stringa są PRZEPISYWANE, nie pomijane. Kosztuje to najwięcej
    /// przy <c>sslmode</c>: bez niego Npgsql zostaje przy domyślnym <c>Prefer</c>,
    /// czyli zgadza się na połączenie NIESZYFROWANE, jeśli serwer tak powie.
    /// A <c>DATABASE_URL</c> z definicji wskazuje bazę inną niż deweloperska —
    /// czyli zwykle zdalną, gdzie <c>sslmode=require</c> jest całym zabezpieczeniem
    /// transportu.
    ///
    /// Nieznany parametr zatrzymuje składanie adresu (builder Npgsql rzuca
    /// <see cref="ArgumentException"/>). Głośny błąd konfiguracji jest lepszy niż
    /// ciche zjedzenie parametru, o którym ktoś myśli, że działa.
    /// </remarks>
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

    /// <summary>`?sslmode=require&amp;pooling=false` → pary klucz-wartość.</summary>
    /// <remarks>
    /// Ręcznie, bo to osiem linijek, a alternatywą jest pakiet w module, który ma
    /// dziś jedną zależność zewnętrzną (Npgsql) i lepiej, żeby tak zostało.
    /// </remarks>
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
